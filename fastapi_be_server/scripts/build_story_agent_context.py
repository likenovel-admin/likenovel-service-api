#!/usr/bin/env python3
"""스토리 에이전트 원문 컨텍스트 적재 배치.

기본 정책
- 대상은 무료 작품 전체
- SSOT는 tb_product_episode.episode_content
- EPUB fallback은 기본 비활성, 필요 시에만 임시 원문으로 사용
- tb_product_episode 자체는 절대 update 하지 않음
- context_doc/context_chunk는 append-only, active 포인터만 전환
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import sys
from collections import Counter
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pymysql
from bs4 import BeautifulSoup
from httpx import AsyncClient, HTTPStatusError, RequestError
from pymysql.constants import CLIENT
from pymysql.cursors import DictCursor

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.const import settings  # noqa: E402
from app.services.common import comm_service  # noqa: E402
from app.services.product.episode_service import _extract_epub_payload_from_epub  # noqa: E402

logger = logging.getLogger(__name__)

DB_HOST = os.getenv("BATCH_DB_HOST", settings.DB_IP)
DB_PORT = int(os.getenv("BATCH_DB_PORT", str(settings.DB_PORT)))
DB_USER = os.getenv("BATCH_DB_USER", settings.DB_USER_ID)
DB_PASSWORD = os.getenv("BATCH_DB_PASSWORD", settings.DB_USER_PW)
DB_NAME = os.getenv("BATCH_DB_NAME", "likenovel")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
EPISODE_SUMMARY_MODEL = os.getenv("STORY_AGENT_SUMMARY_MODEL", "deepseek/deepseek-v3.2").strip()
RP_OPENROUTER_MODEL = os.getenv("STORY_AGENT_RP_OPENROUTER_MODEL", "google/gemma-4-31b-it").strip()
RP_OPENROUTER_PROVIDER_ONLY = os.getenv("STORY_AGENT_RP_OPENROUTER_PROVIDER_ONLY", "deepinfra,together").strip()
DEEPSEEK_OPENROUTER_PROVIDER_ONLY = os.getenv(
    "STORY_AGENT_DEEPSEEK_OPENROUTER_PROVIDER_ONLY",
    "together",
).strip()
RP_OPENROUTER_TIMEOUT_SECONDS = float(os.getenv("STORY_AGENT_RP_OPENROUTER_TIMEOUT_SECONDS", "90"))
CHARACTER_CHAT_INTERNAL_PROMPT_TIMEOUT_SECONDS = float(
    os.getenv("STORY_AGENT_CHARACTER_CHAT_INTERNAL_PROMPT_TIMEOUT_SECONDS", "180")
)
RP_PROFILE_MIN_EXAMPLE_TEXTS = int(os.getenv("STORY_AGENT_RP_PROFILE_MIN_EXAMPLES", "2"))
RP_PROFILE_MAX_TARGETS_PER_PRODUCT = int(os.getenv("STORY_AGENT_RP_PROFILE_MAX_TARGETS_PER_PRODUCT", "2"))
RP_DIALOGUE_FALLBACK_MAX_EPISODES = int(os.getenv("STORY_AGENT_RP_DIALOGUE_FALLBACK_MAX_EPISODES", "18"))
RP_DIALOGUE_FALLBACK_EXCERPT_CHARS = int(os.getenv("STORY_AGENT_RP_DIALOGUE_FALLBACK_EXCERPT_CHARS", "4600"))
RP_REASONING_MODEL = os.getenv("STORY_AGENT_RP_REASONING_MODEL", "").strip()
if RP_REASONING_MODEL.startswith("anthropic."):
    RP_REASONING_MODEL = RP_REASONING_MODEL.split(".", 1)[1].strip()
RP_REASONING_EFFORT = (os.getenv("STORY_AGENT_RP_REASONING_EFFORT", "medium").strip() or "medium")
RP_REASONING_THINKING_DISPLAY = (os.getenv("STORY_AGENT_RP_REASONING_THINKING_DISPLAY", "omitted").strip() or "omitted")
EPISODE_CHARACTER_SIGNALS_MAX_OUTPUT_TOKENS = int(os.getenv("STORY_AGENT_CHARACTER_SIGNALS_MAX_OUTPUT_TOKENS", "2600"))
EPISODE_CHARACTER_SIGNALS_OPENROUTER_MODEL = (
    os.getenv("STORY_AGENT_CHARACTER_SIGNALS_OPENROUTER_MODEL", "").strip()
    or "deepseek/deepseek-v4-pro"
)
EPISODE_CHARACTER_SIGNALS_OPENROUTER_TIMEOUT_SECONDS = float(
    os.getenv("STORY_AGENT_CHARACTER_SIGNALS_OPENROUTER_TIMEOUT_SECONDS", "60")
)
EPISODE_SUMMARY_TIMEOUT_SECONDS = 120.0
EPISODE_SUMMARY_TEMPERATURE = float(os.getenv("STORY_AGENT_SUMMARY_TEMPERATURE", "0.0"))
EPISODE_SUMMARY_MAX_OUTPUT_TOKENS = 1400
EPISODE_SUMMARY_MAX_INPUT_CHARS = 10000

TARGET_CHUNK_LEN = 1600
MAX_CHUNK_LEN = 2500
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+|(?<=다\.)\s+|(?<=요\.)\s+")
KEYWORD_RE = re.compile(r"[가-힣A-Za-z0-9]{2,}")
EPISODE_SUMMARY_FORMAT_VERSION = "episode_summary_v12"
EPISODE_CHARACTER_SIGNALS_FORMAT_VERSION = "episode_character_signals_v3"
RANGE_SUMMARY_FORMAT_VERSION = "range_summary_v1"
PRODUCT_SUMMARY_FORMAT_VERSION = "product_summary_v1"
CHARACTER_SNAPSHOT_FORMAT_VERSION = "character_snapshot_v1"
CHARACTER_INVENTORY_FORMAT_VERSION = "character_inventory_v2"
CHARACTER_INVENTORY_V3_FORMAT_VERSION = "character_inventory_v3"
WORK_PROTAGONIST_RESOLUTION_FORMAT_VERSION = "work_protagonist_resolution_v1"
WORK_PROTAGONIST_RESOLUTION_MAX_OUTPUT_TOKENS = 1200
CHARACTER_INVENTORY_V3_PROTAGONIST_SCORE_THRESHOLD = 0.40
CHARACTER_INVENTORY_V3_DOMINANT_PROTAGONIST_SCORE_THRESHOLD = 0.35
CHARACTER_INVENTORY_V3_DOMINANT_PROTAGONIST_MIN_RATIO = 1.15
CHARACTER_INVENTORY_V3_DOMINANT_PROTAGONIST_MIN_COVERAGE = 0.45
WORK_PROTAGONIST_CO_MAIN_MAX_COUNT = 3
WORK_PROTAGONIST_CO_MAIN_NEAR_TIE_SCORE_RATIO = 0.95
WORK_PROTAGONIST_CO_MAIN_MIN_SCORE = 0.15
WORK_PROTAGONIST_CO_MAIN_HINT_RATIO = 0.80
RELATION_INVENTORY_FORMAT_VERSION = "relation_inventory_v1"
CHARACTER_RP_PROFILE_FORMAT_VERSION = "character_rp_profile_v3"
CHARACTER_RP_EXAMPLES_FORMAT_VERSION = "character_rp_examples_v3"
CHARACTER_CHAT_INTERNAL_PROMPT_FORMAT_VERSION = "character_chat_internal_prompt_v1"
CHARACTER_CHAT_OPENING_FORMAT_VERSION = "character_chat_opening_v1"
CHARACTER_CHAT_OPENING_RUNTIME_FORMULA_CONTRACT_VERSION = "runtime_formula_seed_v1"
CHARACTER_CHAT_RUNTIME_FORMULA_REQUIRED_FIELDS = (
    "formula_type",
    "p_to_user_request",
    "user_task_type",
    "user_task_success_condition",
    "protagonist_state_delta",
    "open_loop",
    "mutation_policy",
)
EPISODE_SCENE_EXTRACTION_FORMAT_VERSION = "episode_scene_extraction_v1"
EPISODE_SCENE_EXTRACTION_MAX_INPUT_CHARS = int(os.getenv("STORY_AGENT_SCENE_EXTRACTION_MAX_INPUT_CHARS", "18000"))
EPISODE_SCENE_EXTRACTION_MAX_OUTPUT_TOKENS = int(os.getenv("STORY_AGENT_SCENE_EXTRACTION_MAX_OUTPUT_TOKENS", "5000"))
EPISODE_SCENE_EXTRACTION_OPENROUTER_MODEL = (
    os.getenv("STORY_AGENT_SCENE_EXTRACTION_OPENROUTER_MODEL", "").strip()
    or "deepseek/deepseek-v4-pro"
)
EPISODE_SCENE_EXTRACTION_OPENROUTER_TIMEOUT_SECONDS = float(
    os.getenv("STORY_AGENT_SCENE_EXTRACTION_OPENROUTER_TIMEOUT_SECONDS", "120")
)
EPISODE_CHARACTER_SIGNALS_TOOL_NAME = "submit_episode_character_signals"
EPISODE_SCENE_EXTRACTION_TOOL_NAME = "submit_episode_scene_extraction"
DIALOGUE_QUOTE_RE = re.compile(r'["“](.*?)["”]', re.S)
FIRST_PERSON_MONOLOGUE_RE = re.compile(
    r"(?<![가-힣A-Za-z0-9])(?:나는|내가|난(?=[^가-힣A-Za-z0-9]|$)|나를|내게|내겐|내 마음|내 생각|내 판단)"
)
SPEECH_VERB_PATTERN = (
    r"(?:말했|말하|말했다|묻|물었|물었다|답했|답하|답했다|대답했|대답했다|외쳤|외쳤다|"
    r"소리쳤|소리쳤다|중얼|중얼거렸|속삭|속삭였|대꾸했|대꾸했다|반박했|반박했다|"
    r"선언했|선언했다|명령했|명령했다|덧붙였|덧붙였다|웃었|웃었다)"
)
RP_SIMPLE_VOCATIVE_RE = re.compile(r"^[가-힣A-Za-z0-9]{2,12}(?:아|야)?[!?.…~]*$")
RP_NOISE_ONLY_RE = re.compile(r"^[!?.…~ㅋㅎㅠㅜ\s]+$")
RP_GENERIC_DISPLAY_NAMES = {"지금", "오늘", "그때", "나", "내", "그", "그녀", "그들", "현재", "이번"}
NON_PERSONA_GENERIC_LABELS = RP_GENERIC_DISPLAY_NAMES | {
    "난", "주인공", "화자", "서술자", "남자", "여자", "소년", "소녀", "청년", "노인", "아이", "인물",
    "형", "형님", "누나", "누님", "언니", "오빠", "동생", "아버지", "아빠", "어머니", "엄마",
    "할아버지", "할아범", "할배", "할머니", "할멈", "조부", "조모", "아저씨", "아줌마", "삼촌", "이모", "고모",
    "피해자",
}
GENERIC_CHARACTER_LABELS = RP_GENERIC_DISPLAY_NAMES | {
    "난", "주인공", "화자", "서술자", "남자", "여자", "소년", "소녀", "청년", "노인", "아이", "인물",
    "형", "형님", "누나", "누님", "언니", "오빠", "동생", "아버지", "아빠", "어머니", "엄마",
    "할아버지", "할아범", "할배", "할머니", "할멈", "조부", "조모", "아저씨", "아줌마", "삼촌", "이모", "고모",
    "왕", "여왕", "폐하", "전하", "황제", "황후", "왕자", "공주", "왕비", "대공", "공작",
    "후작", "백작", "자작", "남작", "영주", "성녀", "성자", "교황", "교주", "사제", "신관",
    "선생", "선생님", "교수", "스승", "사부", "마스터", "대장", "단장", "대장님", "단장님",
    "사장", "사장님", "회장", "회장님", "팀장", "팀장님", "부장", "부장님", "상관", "부하",
    "주군", "주인", "기사", "마법사", "용사", "악마", "신", "괴물", "헌터", "관리자",
    "피해자", "노신사", "노파", "매니저",
}
IDENTITY_CLAIM_TYPES = {
    "same_person_as",
    "alias_of",
    "real_name_of",
    "avatar_name_of",
    "game_name_of",
    "codename_of",
    "possessed_as",
    "self_reference_as",
    "title_of",
}
AUTHORITATIVE_IDENTITY_CLAIM_TYPES = {"same_person_as"}
NAME_VARIANT_IDENTITY_CLAIM_TYPES = {"real_name_of", "alias_of", "codename_of"}
SOCIAL_PERSONA_IDENTITY_CLAIM_TYPES = {"avatar_name_of", "game_name_of", "possessed_as", "codename_of", "self_reference_as"}
TRANSFER_IDENTITY_CLAIM_TYPES = {"avatar_name_of", "game_name_of", "possessed_as", "self_reference_as"}
IDENTITY_TRANSFER_RELATION_TAG_TOKENS = {
    "빙의",
    "환생",
    "전생",
    "전이",
    "아바타",
    "게임명",
}
GENERIC_PROTAGONIST_IDENTITY_SOURCE_LABELS = RP_GENERIC_DISPLAY_NAMES | {"난", "저", "주인공", "화자"}
REAL_NAME_IDENTITY_CLAIM_TYPES = {"real_name_of"}
NON_BLOCKING_INVENTORY_IDENTITY_CONFLICT_REASONS = {
    "unresolved_generic_first_person",
    "duplicate_canonical_key",
}
SOCIAL_DISPLAY_BLOCK_SUBSTRINGS = {
    "같은",
    "놈",
    "녀석",
    "새끼",
    "머저리",
    "미물",
    "아저씨",
    "아가씨",
}
SOCIAL_DISPLAY_BLOCK_SUFFIXES = {
    "씨",
    "님",
    "대표님",
    "나리",
}
IDENTITY_LABEL_BLOCK_WORD_TOKENS = {
    "아들", "딸", "아이", "손자", "손녀", "부친", "모친", "아버지", "어머니", "친아버지", "친어머니",
    "남편", "아내", "부인", "스승", "제자", "형제", "자매", "조부", "조모",
    "과장", "국장", "팀장", "부장", "사장", "회장", "영주", "황자", "황녀",
    "공작", "장군", "기사단장",
    "소지자", "보유자", "출신", "변절자", "배신자", "용의자", "생존자", "죄수",
    "아저씨", "아가씨", "전하", "폐하", "각하", "선생님", "형님",
}
IDENTITY_LABEL_BLOCK_SUFFIX_TOKENS = {
    "과장", "국장", "팀장", "부장", "사장", "회장", "기사단장",
    "소지자", "보유자", "출신", "변절자", "배신자", "용의자", "피해자", "생존자", "죄수",
    "부인", "조부", "조모", "마스터",
}
IDENTITY_LABEL_BLOCK_GROUP_SUFFIX_TOKENS = {
    "부부", "가족", "일가", "일행", "무리",
}
IDENTITY_LABEL_BLOCK_ORDINAL_TITLE_SUFFIX_TOKENS = {
    "황자", "황녀", "왕자", "공주", "황제", "황후",
}
IDENTITY_LABEL_BLOCK_DESCRIPTOR_PATTERNS = (
    re.compile(r"^키큰(?:남자|여자|사람)$"),
    re.compile(r"^노(?:신사|파)$"),
)
SPEAKER_ANCHOR_MIN_CHARS = 2
KOREAN_NAME_PARTICLE_PATTERN = (
    r"(?:은|는|이|가|을|를|과|와|의|에게|한테|께|도|만|부터|까지|처럼|으로|로|아|야)?"
)
DIRECT_VOICE_DIALOGUE_MIN_ITEMS = 8
DIRECT_VOICE_DIALOGUE_MIN_EPISODES = 3
DIRECT_VOICE_DIALOGUE_MIN_CHARS = 200
DIRECT_VOICE_DIALOGUE_MIN_EXAMPLES = 3
DIRECT_VOICE_MONOLOGUE_MIN_ITEMS = 6
DIRECT_VOICE_MONOLOGUE_MIN_EPISODES = 3
DIRECT_VOICE_MONOLOGUE_MIN_CHARS = 300
DIRECT_VOICE_MAX_EPISODE_SHARE = 0.60
RANGE_SUMMARY_EPISODE_SPAN = 20
EPISODE_SUMMARY_FIRST_LINE_RE = re.compile(r"^\[(?P<label>\d+화)\]\s+(?P<title>.+)$")
EPISODE_TITLE_LABEL_RE = re.compile(r"^\s*(?P<label>\d+화)\s*(?P<title>.+?)\s*$")
KEYWORD_STOPWORDS = {
    "그리고", "하지만", "그러나", "이번", "저번", "그녀", "그는", "그것", "이것", "저것",
    "에게", "에서", "한다", "했다", "했다는", "있다", "있는", "없다", "없고", "정도", "처럼",
    "위해", "통해", "이후", "이전", "장면", "회차", "작품", "내용", "상태",
}
CHARACTER_STOPWORDS = KEYWORD_STOPWORDS | {
    "주인공", "조연", "악역", "능력", "시간정지", "발현", "전학생", "전학", "학교", "학생",
    "작전", "전쟁", "요약", "키워드", "장면", "회차", "작품", "사건", "한계", "실전", "결투",
    "강북고", "발동", "처음", "최초", "직후", "순간", "소년", "소녀", "남자", "여자",
    "세계", "사람", "게임", "신화", "인화", "신의", "학교", "도시", "능력자", "헌터",
}
NAME_WITH_PARTICLE_RE = re.compile(r"([가-힣A-Za-z][가-힣A-Za-z0-9]{1,6})(?:은|는|이|가|을|를|과|와|의|에게|한테)")
COMMON_KOREAN_SURNAMES = {
    "김", "이", "박", "최", "정", "강", "조", "윤", "장", "임", "한", "오", "서", "신", "권",
    "황", "안", "송", "류", "홍", "전", "고", "문", "양", "손", "배", "백", "허", "유", "남",
    "심", "노", "하", "곽", "성", "차", "주", "우", "구", "민", "진", "지", "엄", "채", "원",
    "천", "방", "공", "현", "함", "변", "염", "여", "추", "도", "소", "석", "선", "설", "마",
    "길", "연", "위", "표", "명", "기", "반", "왕", "금", "옥", "육", "인", "맹", "제", "모",
    "탁", "국", "어", "은", "편", "용",
}

EPISODE_SUMMARY_SYSTEM_PROMPT = """당신은 웹소설 회차를 검색용 summary_text로 변환하는 전처리기다.
목표는 이 텍스트만 보고도 해당 회차를 다시 찾는 것이다.
설명, 감상, 코드블록, 번호, 불릿을 붙이지 말고 오직 결과 텍스트만 반환하라.

형식 규칙
1. 첫 줄은 반드시 지정된 헤더를 그대로 쓴다.
2. 본문은 회차 전체를 시간순으로 다 적지 말고, 다시 찾기에 가장 중요한 핵심 언행과 사건만 남긴다.
3. 본문은 핵심 사건 3개 이상 5개 이하를 목표로 하되, 정말 필요한 경우만 그보다 적거나 많게 쓴다.
4. 본문 각 줄은 서로 다른 구체 사건 1개를 우선한다.
5. 각 사건 줄은 가능한 한 인물 이름/호칭 + 말하거나 행동한 내용 + 결과를 포함한다.
6. 마지막 줄은 반드시 "핵심:"으로 시작한다.
7. 마지막 줄의 핵심 항목은 정확히 6개 이상 8개 이하, 쉼표로만 구분한다.
8. 본문은 설정 설명만 이어 쓰지 말고, 적어도 2줄 이상은 핵심 인물의 언행이 직접 드러나게 하라.

내용 규칙
1. 사실만 쓴다. 추측, 평가, 감상, 일반론 금지.
2. 원문에 없는 인물, 사건, 설정, 수치, 색상, 감정 해석을 만들지 마라.
3. 고유명사, 인물명/호칭, 능력명, 장비명, 세력명, 수치, 제약, 선택은 원문 표현에 가깝게 보존하라.
4. "갈등 심화", "긴장감 고조", "위기", "변화", "성장", "결심" 같은 추상 표현은 쓰지 마라.
5. 핵심 항목은 추상어보다 인물명, 호칭, 능력명, 장비명, 수치, 제약, 사건 앵커를 우선한다.
6. 정보가 부족하다고 느껴져도 비우지 말고, 원문에서 검색 가치가 높은 구체 사실을 더 추출하라.
7. 중요도가 낮은 중간 과정, 반복 공격 로그, 세부 동작 열거는 생략하라.
8. 한 화의 모든 사건을 다 쓰지 마라. 결정적 사건, 선택, 제약, 전환점만 남겨라.
9. 전투 회차라도 개별 타격 로그를 나열하지 말고, 전세를 바꾼 행동과 결과만 남겨라.
10. 여러 문장이 같은 사건을 설명하면 하나로 합쳐라.
11. 회차를 설명할 때 사건 그 자체보다 먼저 "누가 어떤 태도로 무엇을 말하고 행동했는지"를 잡아라.
12. 설정, 장소, 능력, 규칙은 인물의 말과 행동을 이해하는 데 필요한 정도로만 덧붙여라. 설정 설명만 따로 길게 쓰지 마라.
13. 가능하면 본문 첫 2줄 안에 핵심 인물 1명 이상이 직접 드러나게 하라.
14. 인물의 선택, 반응, 태도 변화가 중요하면 그 언행을 사건보다 우선해서 적어라.
15. 이름이 없는 인물이라도 반복되는 호칭이나 역할어가 있으면 일관되게 보존하라.
16. 한 줄 안에서 여러 인물을 뭉개지 말고, 누가 누구에게 어떻게 반응했는지 관계 방향이 보이게 써라.
17. 대화/말버릇/거절/수락/비꼼/경계/보호 같은 태도 신호가 있으면 설정 설명보다 우선해서 남겨라.
18. 핵심 항목에는 가능하면 인물명 또는 반복 호칭을 2개 이상 포함하라.
19. 인물의 실명 또는 고유 호칭이 원문에 보이면 "주인공", "후배", "아이" 같은 일반 역할어만 단독으로 반복하지 마라.
20. 같은 인물은 한 summary 안에서 가능한 한 같은 이름/고유 호칭으로 유지하라. 실명과 역할어를 섞더라도 실명을 우선하라.
21. "핵심:" 줄에는 일반 역할어보다 실명/고유 호칭을 우선해서 남겨라.
"""

RP_DIALOGUE_COLLECTION_PROMPT = """너는 웹소설 원문에서 특정 캐릭터의 대사만 수집하는 전처리기다.
반드시 JSON만 반환하라. 원문에 없는 정보는 만들지 마라.

직접 말한 대사만 dialogue로 뽑아라.
대상 캐릭터가 청자/호명/목적어인 경우는 speaker가 아니다.
화자가 불명확하면 제외하라.
quote/text는 입력 원문에 존재하는 문자열 그대로여야 한다.
한 회차에서 최대 2개만 뽑고, 가능하면 4개 이상 서로 다른 회차에서 뽑아라.

출력 스키마:
{"items":[{"episode_no":1,"kind":"dialogue","context":"상황 10자 이내","text":"원문 그대로","speaker_label":"화자명","confidence":0.0}]}
"""

RP_PROFILE_SYNTHESIS_PROMPT = """너는 웹소설 캐릭터 RP 프로필 합성기다.
반드시 JSON만 반환하라. 대사에 없는 정보는 만들지 마라.

출력 스키마:
{
  "speech_style": {
    "tone": ["차가운"],
    "formality": "반말|존대|상황따라",
    "sentence_length": "짧게 끊는|보통|장문",
    "habit": ["원문 표현"],
    "address": "상대를 뭐라고 부르는지"
  },
  "personality_core": ["대사에서 드러나는 성격 1", "대사에서 드러나는 성격 2"],
  "baseline_attitude": "경계|무난|친근|차가움|무심함",
  "example_dialogues": ["가장 캐릭터다운 대사 5개"]
}

규칙:
0. 입력 후보 중 대상 캐릭터가 아닌 것으로 보이거나 화자가 불분명한 줄은 무시하라.
1. habit은 2회 이상 반복된 표현만 넣어라.
2. example_dialogues는 다른 캐릭터는 잘 하지 않을 말만 고르고, 인사/감탄사/상황설명은 제외하라.
3. example_dialogues에는 dialogue만 사용하고 monologue는 넣지 마라.
4. example_candidate 표시가 붙은 줄을 우선 사용하고, source 표기 줄은 후보가 부족할 때만 사용하라.
5. 이름만 부르는 말, 한두 단어 반응, 의미 약한 짧은 말은 example_dialogues로 고르지 마라.
6. 짧은 사과, 단순 수락, 상태 보고, 예의상 대답처럼 누구나 할 수 있는 일반 반응은 example_dialogues로 고르지 마라.
7. example_dialogues는 단독으로 봐도 태도, 관계, 말버릇이 드러나는 문장만 고르라.
8. personality_core와 baseline_attitude는 아래 summary_context를 보조 근거로 사용할 수 있다. 하지만 speech_style, habit, example_dialogues는 반드시 dialogue 근거만 사용하라.
9. personality_core는 대사와 summary_context에서 직접 드러나는 것만 쓰고 추측하지 마라.
10. summary_plan에 반응축이 주어졌다면, example_dialogues는 가능한 한 서로 다른 반응축을 대표하게 고르라. 같은 결의 대사만 여러 개 고르지 마라.
11. 가능하면 반응축마다 대표 대사 1개씩 먼저 고르고, 축이 부족할 때만 같은 축의 대사를 추가하라.
"""

CHARACTER_CHAT_INTERNAL_PROMPT_SYSTEM = """너는 웹소설 원고 기반 캐릭터챗 내부 프롬프트 설계자다.
반드시 JSON만 반환하라. 원문/요약/관계/대사 근거에 없는 설정을 만들지 마라.

목표:
- 아래 입력만으로 매 턴 캐릭터 답변을 밀어주는 '1:1 캐릭터챗 내부 프롬프트'를 작성한다.
- 출력 형식 가드가 아니라, 캐릭터의 정체성/말투/상황 반응/관계 리듬을 유지하는 본체 프롬프트여야 한다.
- 작품 Q&A가 아니라 사용자가 캐릭터와 같은 장면에 이미 엮인 듯한 역할극을 전제로 한다.
- 런타임의 하드 렌더링 가드가 이 내부 프롬프트보다 우선한다. 내부 프롬프트도 그 가드를 거스르지 않게 작성한다.

출력 스키마:
{"internal_prompt":"1600~3200자 한국어 내부 프롬프트"}

internal_prompt 필수 구성:
1. [핵심 정체성]: 이름/별칭/작품 속 역할. 회빙환/빙의/가명/호칭이 있으면 등장인물이 실제로 부르는 이름을 우선하되, 근거가 있는 별칭만 쓴다.
2. [캐릭터성/말투]: 성격, 판단 기준, 말투, 호칭, 문장 리듬. 실제 대사 근거와 모순되면 안 된다.
3. [관계와 거리감]: 사용자를 이미 장면에 엮인 비네임드 조력자/동행자/관계자로 대하는 기본 거리감, 경계/호감/협력 변화 조건. 사용자의 정체를 캐묻는 미스터리로 만들지 않는다.
4. [첫인사 오프닝]: 사용자가 아직 말하기 전 캐릭터가 먼저 말을 거는 장면을 어떻게 열지 쓴다. 장소의 공기/소리/빛, 캐릭터의 자세/시선/거리, 사용자를 붙잡는 즉각적 긴장, 첫 대사의 상황 질문/협력 요청/선택 여지 hook을 포함한다.
5. [시작/현재 장면 운용]: 읽은 범위 기준 앵커를 받아 그 시점에서 확인 가능한 장소, 긴장, 행동만 사용한다. 시작 장면을 매 턴 리셋하지 않는다.
6. [원작 기반 새 사건 운용]: 원작 세계관, 설정, 인물성, 읽은 범위의 갈등은 최대한 유지하되 원작 사건을 그대로 재연하지 않는다. 원작 플롯은 앵커로만 쓰고, 답변의 중심은 원작에서 파생된 새 사이드 사건/새 변수/새 단서여야 한다. 새 사건의 비중을 원작 요약보다 높게 두되, 새 사건은 기존 세계관과 캐릭터 동기에서 자연스럽게 생긴 작은 위기, 요청, 방해, 단서, 관계 압력이어야 한다. 원작 결말/배후/미래 사건을 새로 확정하지 않는다.
7. [런타임 전개 공식]: 캐릭터가 유저에게 맡길 1~3턴짜리 구체 작업, 그 작업이 영향을 줄 주인공의 다음 행동, 작업 뒤 생길 state_delta/open_loop를 함께 둔다. 유저 작업은 관찰/추론/타이밍/선택/증거/경로/반응 읽기처럼 즉시 답할 수 있어야 하며 최종 승리나 결말이 아니어야 한다.
8. [짧은 입력 처리]: 사용자가 '응', '그래', '뭐야?'처럼 짧게 말해도 캐릭터가 지문+대사로 반응하고 작은 사건/질문/행동 하나, 또는 새 변수/관계 반응/장면 변화 하나로 장면을 전진시킨다.
9. [사용자 agency]: 사용자가 직전 입력에서 직접 밝힌 행동/말/상태만 이어받는다. 캐릭터는 자신의 행동을 먼저 할 수 있지만 사용자의 감정/반응/성공/다음 행동은 확정하지 않는다. 협력 요청은 선택 가능하게 남긴다. 사용자의 정체를 심문하는 반복 전개, 원작 기존 인물로의 확정, 공개 읽은 범위 밖 스포일러, 메타 발언, 원문 대사 복붙은 만들지 않는다.
10. [응답 감각]: 첫인사는 5~8문장 지문 + 2~3문장 대사로 장면을 충분히 연다. 이후 답변은 지문 2~4문장 뒤 캐릭터 대사 1~3문장을 기본으로 하되, 매 턴 물리적 행동/새 변수/관계 반응/장면 변화/hook 하나를 둔다.

규칙:
- 정보가 부족하면 모른다고 해설하지 말고, 확인 가능한 현재 장면의 반응으로 좁혀라.
- 단순 목록보다 실제 런타임에서 바로 먹히는 지시문 문체로 작성하라.
- 예시는 말투 기준으로만 짧게 포함하고, 원문 대사를 길게 인용하지 마라.
- 첫인사는 일반 인사말이 아니라 독자가 스크롤을 멈출 만큼 구체적인 장면 진입이어야 한다.
- 사용자는 원작 기존 네임드가 아니라 이미 장면에 엮인 비네임드 조력자/동행자/관계자다. 기본 역할은 낮은 신뢰의 협력자, 임시 동행자, 현장 보조자, 목격자, 같이 휘말린 사람 중 장면에 맞게 약하게만 둔다.
- 캐릭터가 경계심이 강해도 의심은 말투 한 줄 이하로만 두고, 정체 심문을 사건 엔진으로 쓰지 마라. 첫인사는 현재 사건의 목적, 위기, 행동 hook으로 열어라.
- 치료 보조, 기록 담당, 임시 동행자, 현장 보조자처럼 장면을 돕는 약한 역할 라벨은 가능하지만 사용자를 원작 기존 네임드/짐승/환자/포로로 확정하지 마라.
- 원작은 대본이 아니라 제약 조건이다. 원작 장면을 요약하거나 반복하지 말고, 읽은 범위의 갈등/관계/장소/물건에서 파생된 새 곁가지 사건으로 시작하라.
- 전개 공식은 `공개 평가 뒤집기`, `초기 자원 확보`, `전투 패턴 깨기`, `불확실한 인물의 신뢰 전환`, `작은 사건의 확장` 중 입력 근거와 가장 가까운 것을 우선 사용하라. 장면마다 유저에게 관찰/단서 확인/타이밍 콜/선택지 계산/답변 작성/경로 파악/증거 준비 중 하나를 맡기고, 캐릭터가 그 결과를 자신의 행동 변화로 받아 장면을 전진시키게 하라.
- 캐릭터는 장면 목적과 stake를 제공하되, 사용자를 심부름시키는 명령문보다 장면 압력, 협력 요청, 자연스러운 1~2개 행동 방향으로 유도하라.
- 사건 진행만 밀지 말고, 사용자의 말에 대한 캐릭터의 관계 반응을 최소 하나 포함하게 하라.
- 압박감과 관계 반응은 캐릭터 자신의 자세/행동/판단, 주변 사물, 출입구, 환경 변화, 대사로 만든다.
- 사용자가 직전 입력에서 직접 묘사한 행동과 상태는 이어받을 수 있지만, 입력에 없는 사용자 행동/상태/소지품/관계/결과를 덧붙이지 않는다.
- 캐릭터 자신의 접근/시선/접촉은 캐릭터 행동으로 쓸 수 있으나, 그에 대한 사용자의 감정과 반응은 다음 입력 전에 확정하지 않는다.
- 사용자의 말에 대한 협력 요청은 대사 안에서 선택 가능하게 남기고, 사용자의 실행과 결과는 다음 입력 전에 확정하지 않는다.
- 내부 프롬프트에 구체적인 금지 표현 목록을 만들지 마라. 출력 전에는 사용자에 관한 서술마다 직전 입력의 근거가 있는지 확인하게 하라.
"""

EPISODE_SCENE_EXTRACTION_SYSTEM = """너는 웹소설 원문을 캐릭터챗용 장면 단위로 나누는 전처리기다.
반드시 JSON만 반환하라. 첫인사, RP 대사, 새 사건, 감상평을 만들지 마라.

목표:
- 회차 원문에서 캐릭터가 움직일 수 있는 핵심 장면 2~3개를 고른다.
- 각 장면은 원문에 실제로 있는 시작 앵커(boundary_anchor_start)를 가져야 한다.
- boundary_anchor_start는 원문에서 그대로 찾을 수 있는 8~80자 문자열이어야 한다.
- 인물 scope_key는 입력의 canonical_character_packet에 있는 값만 사용한다. 모르면 scope_key를 null로 둔다.
- 원문에 없는 인물, 장소, 목적, 감정을 만들지 않는다.
- 캐릭터챗 첫인사나 프롬프트를 쓰지 말고 장면 재료만 추출한다.
- 전체 JSON은 간결하게 쓴다. 장면당 participants 최대 3명, action_ownership 최대 2개, scene_gist 최대 60자.
- 캐릭터챗 재료이므로 주인공/대상 캐릭터가 현장에 등장해 직접 판단, 행동, 대화, 관계 반응을 하는 장면을 최우선으로 고른다.

출력 스키마:
{
  "schema_version": "episode_scene_extraction_v1",
  "status": "ok|partial|failed",
  "scenes": [
    {
      "scene_index": 1,
      "boundary_anchor_start": "원문 그대로 시작 앵커",
      "scene_kind": "dialogue|action|conflict|exposition|transition|mixed",
      "scene_gist": "장면에서 실제로 벌어진 일 1문장",
      "current_action": "캐릭터가 이 장면에서 이미 하고 있는 행동",
      "immediate_pressure": "지금 장면을 밀어붙이는 위기/목표/갈등",
      "character_initiative_reason": "캐릭터가 유저에게 먼저 말을 걸 수밖에 없는 이유",
      "user_entry_role": "유저가 이 장면에 들어올 때 가장 자연스러운 약한 역할",
      "user_hook": "캐릭터가 유저에게 던질 수 있는 선택/협력 hook",
      "user_can_do": ["유저가 할 수 있는 약한 행동 선택지"],
      "opening_grounding": {
        "place_anchor": "첫인사 지문에 써도 되는 원문 기반 장소/공간",
        "sensory_anchors": ["원문 근거가 있는 소리/빛/냄새/온도/군중감"],
        "prop_anchors": ["원문 근거가 있는 물건/무기/문서/장치"],
        "spatial_constraints": ["문 앞|복도 끝|마차 안처럼 원문 근거가 있는 공간 제약"],
        "character_visible_motion": "캐릭터가 원문에서 실제로 보이는 자세/움직임",
        "forbidden_opening_inventions": ["원문에 없으면 첫인사에 만들지 말아야 할 장식"]
      },
      "scene_identity_boundary": {
        "allowed_address_names": ["현재 장면에서 유저가 써도 자연스러운 이름/호칭"],
        "must_not_address_as": ["현재 장면에서 먼저 쓰면 스포/오인인 이름/정체"],
        "surface_role_for_user": "유저가 약하게 인식해도 되는 사회적 표면 역할",
        "identity_spoiler_risk": "low|medium|high"
      },
      "pressure_clock": "3~5턴 안에 악화되거나 변하는 압박",
      "conversation_fuel_tags": ["협상|수사|훈련|생존|방송|작전|관계압력 등 최대 3개"],
      "beat_ladder": ["초기 긴장 -> 선택 -> 작은 결과처럼 장면을 전진시키는 단계"],
      "turn_continuation_contract": {
        "state_variables": ["장면 안에서 20턴 동안 변할 수 있는 상태"],
        "user_response_branches": {
          "accepts_hook": "유저가 협력하면 생기는 작은 변화",
          "asks_question": "되물음에 답한 뒤 장면을 전진시키는 방식",
          "refuses_or_delays": "거절/주저에도 막히지 않는 대안",
          "short_or_ambiguous": "응/그래/뭐야 같은 짧은 입력 처리",
          "hostile_or_suspicious": "심문 루프 없이 넘기는 방식"
        },
        "stall_breaker": "2턴 이상 제자리일 때 투입할 작은 방해/단서/관계 반응",
        "scene_exit_condition": "이 장면을 끝내고 다음 장면으로 넘길 조건",
        "canon_safe_new_event_types": ["작은 방해|새 단서|관계 압력|주변 소음|시간 압박"]
      },
      "knowledge_boundary": {
        "can_hint": ["암시 가능하지만 단정하면 안 되는 정보"],
        "must_not_reveal": ["이 장면/읽은 범위에서 직접 말하면 안 되는 정보"]
      },
      "progression_seed": "다음 3~5턴 안에 장면을 전진시킬 작은 변화",
      "participants": [
        {"mention_label": "원문 표시명", "scope_key": "canonical scope_key 또는 null", "evidence": "원문 근거 짧게"}
      ],
      "action_ownership": [
        {"actor_scope_key": "canonical scope_key 또는 null", "action": "그 인물이 한 행동/결정"}
      ]
    }
  ]
}

규칙:
1. 장면은 시간/장소/행동 목적/대화 상대가 바뀌는 지점에서만 나눈다.
2. boundary_anchor_start는 요약문이 아니라 원문 일부여야 한다. 줄번호 표기는 넣지 마라.
3. canonical scope_key가 확실하지 않으면 절대 새 scope_key를 만들지 마라.
4. scene_gist는 장면 목적과 압력만 쓰고, 원작 이후 전개나 결말을 추측하지 마라.
5. 원문 전체를 빠짐없이 요약하려 하지 말고 캐릭터챗에서 재사용 가능한 핵심 장면을 고른다.
6. evidence에는 L0001 같은 라인 prefix를 넣지 말고 원문 표현만 짧게 넣어라.
7. 중요하지 않은 단역/동물/장소/직책은 participants에 넣지 마라.
8. 먼저 주인공/대상 캐릭터가 실제로 현장에 등장하는 장면을 최대 3개까지 찾는다. 원문에 그런 장면이 2개 미만이면 1개만 내도 된다.
9. 가능하면 모든 scene의 participants에 주인공/대상 캐릭터의 canonical scope_key를 포함하라. 단, 원문상 그 인물이 실제로 등장하거나 행동/판단의 중심일 때만 포함한다.
10. 주인공/대상 캐릭터가 현장에 없는 배경, 적대자 회의, 설명 장면은 핵심 장면을 고른 뒤에도 회차 전개 이해에 꼭 필요할 때만 최대 1개 고른다.
11. current_action은 원문 장면에서 캐릭터가 실제로 하는 행동/판단만 쓴다. 성격 설명이나 장르 설명을 쓰지 마라.
12. immediate_pressure는 첫인사에서 바로 걸 수 있는 압력이어야 한다. "자기소개", "상황 설명"처럼 정지된 문구는 쓰지 마라.
13. character_initiative_reason은 캐릭터가 먼저 말을 걸 이유다. 사용자의 정체를 캐묻는 미스터리로 만들지 말고 현재 사건/압력/협력 필요에서 뽑아라.
14. user_entry_role은 원작 네임드가 아니라 장면에 약하게 엮일 수 있는 비네임드 역할만 쓴다. 예: 임시 동행자, 현장 보조자, 의뢰인, 기록 담당, 파티원, 목격자.
15. user_hook과 user_can_do는 사용자의 행동/감정/소지품을 확정하지 말고 캐릭터가 대사로 제안할 수 있는 선택/협력 요청만 쓴다.
16. opening_grounding은 첫인사 지문에서 안전하게 쓸 수 있는 원문 물성만 넣는다. 원문에 없는 비, 달빛, 피 냄새, 골목, 접촉, 자세를 만들지 마라.
17. scene_identity_boundary는 현재 장면에서 공개 가능한 이름/호칭과 먼저 꺼내면 안 되는 정체를 분리한다. 동일인 bridge가 있어도 공개 가능성은 별도다.
18. pressure_clock과 beat_ladder는 20턴 이상 대화가 제자리 반복되지 않도록 장면이 어떻게 조금씩 악화/전진하는지 쓴다.
19. turn_continuation_contract는 유저가 협력/질문/거절/짧은 답/도발을 해도 심문 루프 없이 장면을 전진시키는 정책만 쓴다.
20. conversation_fuel_tags는 장면을 오래 끌 수 있는 루프만 최대 3개 고른다. 태그를 많이 붙이지 마라.
21. knowledge_boundary는 읽은 범위에서 암시 가능한 것과 직접 말하면 안 되는 것을 분리한다. 원작 미래 사건을 새로 확정하지 마라.
22. progression_seed는 원작 장면 복붙이 아니라 3~5턴 안에 새 곁가지 사건, 관계 반응, 위치 변화, 단서, 방해로 장면을 전진시킬 씨앗만 쓴다.
"""

CHARACTER_CHAT_OPENING_SYSTEM = """너는 웹소설 원작 기반 캐릭터챗의 첫 진입 자산 생성기다.
반드시 JSON object 하나만 반환하라. 코드블록, 설명, 머리말 금지.

목표:
- 입력된 캐릭터 인벤토리, RP 프로필, 대표 대사, 내부 프롬프트, 장면 프레임만 사용한다.
- 캐릭터가 먼저 말을 걸 수 있는 몰입형 opening asset을 만든다.
- 원작 세계관과 읽은 범위의 사실은 유지하되, 원작 사건 복붙이 아니라 장면에서 자연스럽게 파생되는 작은 새 사건/압박/hook을 중심에 둔다.
- 유저는 원작 네임드가 아니라 장면에 약하게 엮인 비네임드 조력자/동행자/목격자다.
- 유저 정체 추궁, 심문 루프, "무엇을 도와줄까"식 일반 인사는 금지다.
- 사용자의 행동, 감정, 자세, 소지품, 신체 반응을 지문에서 확정하지 않는다.

출력 스키마:
{
  "readiness": {"status": "ready|needs_review|not_ready", "confidence": 0.0, "block_reasons": []},
  "chat_target": {"scope_key": "입력 scope_key", "display_name": "캐릭터명", "aliases": []},
  "opening_scene": {
    "situation": "첫 진입 장면",
    "immediate_conflict": "즉시 압박",
    "props_or_anchors": [],
    "nearby_characters": []
  },
  "opening_message": {
    "narration": "첫 화면에 그대로 쓸 300~500자 서술형 지문. 캐릭터/환경/사물/사건만 묘사",
    "dialogue": "캐릭터가 직접 말하는 1~3문장의 첫 대사",
    "opening_text": "서술형 지문 문단 + 빈 줄 + 큰따옴표 대사로 합친 첫 assistant 응답 초안",
    "user_objective": "유저가 첫 답변에서 무엇을 하면 되는지"
  },
  "user_role": {
    "role_type": "임시 조력자|동행자|목격자|의뢰인|동료|불명",
    "relationship_to_character": "약한 관계",
    "scene_entry_reason": "유저가 지금 장면에 있는 이유",
    "first_turn_affordance": "첫 답변에서 할 수 있는 약한 선택"
  },
  "character_drive": {
    "immediate_objective": "캐릭터의 지금 목표",
    "pressure": "압박/위험/제약",
    "longer_desire": "초반 큰 욕망"
  },
  "agency_contract": {
    "character_moves_first": true,
    "non_user_dependent_action": "유저가 침묵해도 캐릭터가 다음에 할 행동",
    "decision_character_must_make": "캐릭터가 곧 선택할 결정",
    "user_influence_boundary": "유저가 영향을 줄 수 있지만 대신 주도하지 않는 범위"
  },
  "progression_engine": {
    "short_term_goal": "첫 5~10턴 목표",
    "mid_term_escalation": "10~30턴 사이 새 압박",
    "scene_exit_condition": "다음 국면으로 넘어가는 조건"
  },
  "runtime_formula_seed": {
    "formula_type": "FORMULA_* 라벨. 우선 후보: FORMULA_PUBLIC_TEST_FLIP|FORMULA_RESOURCE_BOOTSTRAP|FORMULA_COMBAT_PATTERN_BREAK|FORMULA_ALLY_TRUST_CONVERSION|FORMULA_CASE_TO_NETWORK",
    "p_to_user_request": "캐릭터가 유저에게 맡기는 1~3턴짜리 구체 작업",
    "user_task_type": "UT_* 라벨. 우선 후보: UT_MONITOR_REACTION|UT_INSPECT_CLUE|UT_CALL_TIMING|UT_CALCULATE_OPTION|UT_CRAFT_RESPONSE|UT_MAP_ROUTE|UT_PREPARE_EVIDENCE|UT_MONITOR_STATUS",
    "user_task_success_condition": "유저가 짧은 응답으로 달성할 수 있는 즉시 성공조건",
    "protagonist_state_delta": "유저 응답 뒤 캐릭터가 행동으로 만들 상태 변화",
    "open_loop": "다음 3~5턴으로 남길 새 변수/위험/단서",
    "mutation_policy": "MP_SAME_RELATION_NEW_TEST|MP_SAME_PRESSURE_NEW_ROUTE|MP_SAME_CASE_NEW_SCOPE|MP_SAME_ASSET_NEW_CLUE|MP_SAME_HAZARD_NEW_LOCATION|MP_SAME_RULE_NEW_EXCEPTION|MP_SAME_DEADLINE_NEW_OBSTACLE|MP_SAME_RIVAL_NEW_MOVE"
  },
  "user_affordance_contract": {
    "primary_affordances": [],
    "forbidden_agency_load": [],
    "safe_response_examples": []
  },
  "canon_safe_expansion": {
    "safe_new_event_pattern": "읽은 범위에서 파생 가능한 새 사건 패턴",
    "allowed_inventions": [],
    "forbidden_inventions": [],
    "must_preserve_facts": []
  },
  "progression": {
    "opening_greeting_intent": "첫 인사가 달성할 목적",
    "next_beats": [{"beat": "다음 전개", "trigger": "유저 반응 조건", "avoid_repeating": "반복 금지"}],
    "anti_loop_rules": []
  }
}

규칙:
1. readiness.status는 장면 프레임, 캐릭터 목표, 유저 역할, 다음 전개가 모두 있을 때만 ready다.
2. chat_target.scope_key는 입력 scope_key와 정확히 같아야 한다.
3. opening_message는 실제 첫 assistant 응답 초안이다. 일반 캐릭터챗 위저드의 첫시작처럼 intro(서술형 지문) + first_line(첫대사) 구조로 만든다. 대사만 있거나 지문만 있으면 ready가 아니다.
4. 유저를 특정 원작 인물, 연인, 가족, 포로, 환자, 짐승, 주인공으로 확정하지 마라.
5. 캐릭터가 장면 목적과 stake를 제공하고, 대화가 20~30턴 반복되지 않게 progression_engine을 채워라.
6. runtime_formula_seed는 반드시 progression_engine과 같은 사건을 가리켜야 한다. 첫 턴에서 유저가 할 일은 최종 payoff가 아니라 관찰/단서 확인/타이밍 콜/선택지 계산/답변 작성/경로 파악/증거 준비처럼 1~3턴 안에 끝나는 작은 작업이어야 한다. 그 작업 뒤 캐릭터가 어떻게 움직일지 protagonist_state_delta와 open_loop를 채워라.
7. runtime_formula_seed.formula_type은 장르가 아니라 장면을 움직이는 행동 공식이다. 공개 평가를 뒤집는 장면은 FORMULA_PUBLIC_TEST_FLIP, 첫 자원/장비/접근권을 만드는 장면은 FORMULA_RESOURCE_BOOTSTRAP, 적의 패턴/위험 동선을 깨는 장면은 FORMULA_COMBAT_PATTERN_BREAK, 불확실한 인물을 협력자로 바꾸는 장면은 FORMULA_ALLY_TRUST_CONVERSION, 작은 단서가 더 큰 사건으로 번지는 장면은 FORMULA_CASE_TO_NETWORK를 우선 고른다. 이 다섯 가지가 맞지 않으면 입력 근거에 가장 가까운 다른 FORMULA_* 라벨을 사용하되 새 라벨을 만들지 마라.
8. opening_message.narration은 300~500자 분량의 서술형 지문이다. 사건 한복판에서 시작하고, 빛/소리/온도/냄새 중 1~2개 감각 디테일, 캐릭터의 3인칭 행동, 즉시 압박, 관계 훅을 넣어라.
9. opening_message.narration은 캐릭터/환경/사물/사건만 묘사한다. 지문에서 사용자의 행동, 감정, 자세, 소지품, 신체 반응, 위치를 확정하지 마라.
10. opening_message.dialogue는 chat_target 캐릭터가 직접 말하는 1~3문장 대사여야 한다. 대사 안에는 유저가 지금 할 수 있는 구체 행동/선택/협력 요청을 넣어라.
   단, 대사에서도 사용자가 이미 멍하니 서 있다/숨어 있다/어슬렁거린다/침입했다/허가받지 않았다/목적을 숨긴다/대답해야 한다고 단정하지 마라.
   협력 요청은 "저 박스 근처로 누가 다가오면 알려", "왼쪽 문양과 오른쪽 발소리 중 하나를 확인해"처럼 외부 사물과 선택지를 향해야 한다.
   첫 대사는 "거기,"로 시작하지 마라. 사용자를 부르는 대신 곧바로 외부 사건/사물/선택지를 제시하라.
   좋은 형식: "저 박스 근처로 누가 다가오면 바로 알려. 나는 이 상태창부터 확인할게." / "왼쪽 문양과 오른쪽 발소리 중 하나를 먼저 봐. 둘 다 놓치면 늦어."
11. opening_message.opening_text는 첫 화면에 그대로 띄울 순수 본문이다. 반드시 `narration` 문단, 빈 줄, 큰따옴표 대사 순서로 작성하라. 단답 대사, 안내문, 자기소개, "무엇을 도와줄까"식 일반 인사는 금지다.
"""

RP_CHARACTER_PLAN_PROMPT = """너는 웹소설 episode_summary를 보고 RP용 중심인물 계획을 세우는 추론기다.
반드시 JSON만 반환하라. 작품 속 실제 인물만 골라라.

출력 스키마:
{
  "characters": [
    {
      "display_name": "캐릭터 표시 이름",
      "aliases": ["별칭"],
      "is_protagonist": true,
      "is_first_person": false,
      "personality_hypothesis": ["성격 가설 1", "성격 가설 2"],
      "interaction_axes": ["반응 축 1", "반응 축 2", "반응 축 3"],
      "baseline_attitude_hypothesis": "경계|무난|친근|차가움|무심함",
      "evidence_episodes": [1, 3, 5],
      "collection_rules": {
        "use_dialogue": true,
        "use_monologue": false,
        "speaker_anchors": ["표시 이름", "별칭"],
        "exclude_tokens": ["인물이 아닌 토큰"],
        "priority_patterns": ["선택 직후 반응", "갈등 장면 대사"]
      }
    }
  ]
}

규칙:
1. 중심인물 3~4명만 고른다. 주인공은 반드시 포함한다.
2. 장소, 조직, 학교, 마법, 장비, 세력, 직책, 일반명사, 서술어 파생 토큰은 절대 캐릭터로 고르지 마라.
3. episode_summary의 핵심 사건과 관계를 보고 실제 인물만 고른다.
4. 1인칭 서술 작품이면 주인공은 is_first_person=true로 둔다.
5. personality_hypothesis는 정확히 2개만 쓴다. episode_summary에서 직접 드러나는 범위만 쓴다.
6. interaction_axes는 이 캐릭터가 자유대화에서 자주 보일 반응 축 3~5개를 짧게 쓴다. 작품마다 다르게 잡고, 전역적인 감정 분류를 억지로 맞추지 마라.
7. speaker_anchors에는 실제로 원문에서 화자/호칭 앵커로 쓸 만한 이름, 별칭, 호칭만 최대 4개 넣는다.
8. exclude_tokens에는 인물 오탐 가능성이 높은 명사(장소, 조직, 마법, 학교, 사물)를 3~6개만 넣는다.
9. evidence_episodes는 이 인물의 성격/관계가 비교적 잘 드러나는 회차만 3~4개 고른다.
10. priority_patterns는 2~3개만 넣는다.
"""

EPISODE_CHARACTER_SIGNALS_PROMPT = """너는 웹소설 회차 요약에서 캐릭터 구조화 신호를 추출하는 분석기다.
원문에 없는 정보는 만들지 마라.
반드시 제공된 JSON schema에 맞는 JSON object만 반환하라.
설명문, 코드블록, 머리말, 꼬리말은 금지한다.

최상위 필드:
- episode_no: 회차 번호
- mentioned_characters: 인물 1~6명
- cliffhanger_hooks: 다음 전개 예측에 필요한 미해결 훅 0~3개

규칙:
1. CHAR는 1명 이상 6명 이하를 목표로 한다.
2. 실제 인물 또는 반복 역할명만 넣고, 장소/조직/사물/기술명은 넣지 마라.
3. 이름이 없더라도 같은 인물로 반복되는 역할명은 stable_role로 넣을 수 있다.
4. is_work_protagonist는 작품 전체 주인공일 때만 true다. 회차에서 lead여도 작품 주인공이 아니면 false다.
5. is_episode_focal은 이 회차의 중심 인물이면 true다. 작품 주인공이 아니어도 회차 중심이면 true일 수 있다.
6. is_protagonist는 legacy 호환 필드이며 is_work_protagonist와 같은 값으로 둔다.
7. 1인칭 서술이 강하고 화자가 작품 전체 주인공이면 is_work_protagonist=true, is_protagonist=true, is_first_person=true로 둔다.
8. display_name에는 "주인공", "선배", "아저씨", "아이" 같은 generic 호칭보다 실제 이름/반복 별칭을 우선한다.
   1인칭 화자의 실제 이름/반복 별칭이 없으면 display_name="나"로 두고, 연구 주제/대화 주제/사건명/상태어를 이름처럼 쓰지 마라.
9. narration_names에는 서술자가 그 인물을 지칭하는 이름을 넣고, social_call_names에는 다른 인물이 그 인물을 부르는 호칭을 넣는다.
   - social_call_names는 identity merge 근거가 아니라 말투/거리감 근거다. display_name을 바꾸기 위해 쓰지 마라.
   - 한국 웹소설 호칭/거리감 신호(예: 전하, 폐하, 도련님, 아가씨, 공자, 대장, 팀장, 대표님, 선생님, 교수, 헌터, 선배, 후배, 형님, 사부, 사형, 장로, 낭자)는 실제 대사/요약에 드러나면 social_call_names에 넣는다.
   - "형", "누나", "아저씨", "주인공", "아이"처럼 일반 관계어는 반복되어 한 인물을 안정적으로 가리키는 경우에만 social_call_names에 넣고, display_name으로 승격하지 마라.
10. 회빙환/빙의/게임/가명처럼 사회적으로 통용되는 현재 정체성 이름은 persona_names에 넣고, 현실/전생/본명은 real_names에 넣는다.
11. action과 affect는 짧은 한국어 태그 0~4개만 넣는다. 없으면 비워도 된다.
12. REL은 실제로 드러난 관계만 넣는다. 애매하면 생략한다.
13. identity_claims는 같은 인물임이 명시적으로 드러날 때만 넣는다. 본명/별명/게임명/아바타명/빙의명/자칭처럼 동일 인물 관계만 허용한다.
   - 같은 인물의 현실 이름/본명/게임명/아바타명/빙의 대상/자칭이 한 요약 안에서 명시되면 반드시 identity_claims에 넣는다.
   - 예: "호영이 조렌 테이머의 부활 중 빙의된 수호자"라면 호영 item에 target_label="조렌 테이머", claim_type="possessed_as"를 넣는다.
   - 단순 직책, 소속, 가족/상하관계, 상태 설명, 같은 장면 등장은 identity_claims로 만들지 않는다.
14. HOOK은 0~3개만 넣는다.
"""

WORK_PROTAGONIST_RESOLUTION_PROMPT = """너는 웹소설 작품 전체의 주인공을 판정하는 분석기다.
반드시 제공된 후보 중 1~3명을 고르거나 UNRESOLVED를 반환하라.
새 인물을 만들거나, 후보를 병합하거나, 후보의 이름을 바꾸지 마라.
반드시 JSON object만 반환하고 설명문, 코드블록, 머리말, 꼬리말은 금지한다.
반드시 아래 키 이름만 사용하라. resolution, selected_canonical_character_key, selected_display_name, reason 키는 금지한다.

출력 JSON:
{
  "schema_version": "work_protagonist_resolution_v1",
  "decision": "RESOLVED" 또는 "UNRESOLVED",
  "work_protagonist_key": "첫 번째 후보 canonical_character_key" 또는 null,
  "work_protagonist_keys": ["후보 canonical_character_key"],
  "confidence": "high" 또는 "medium" 또는 "low",
  "reason_code": "single_clear" 또는 "co_main_protagonists" 또는 "pov_shift_same_protagonist" 또는 "persona_rename_same_person" 또는 "side_arc_not_protagonist" 또는 "ambiguous_dual_lead" 또는 "insufficient_evidence",
  "rationale": "짧은 판단 근거",
  "rejected": [{"key": "후보 canonical_character_key", "reason": "짧은 제외 이유"}],
  "safety_flags": {
    "requires_identity_merge": false,
    "selected_candidate_eligible": true 또는 false,
    "multiple_plausible_main_candidates": true 또는 false
  }
}

규칙:
1. 작품 전체 주인공은 회차 단위 속성이 아니다.
2. 서술 시점, 회차 초점, 사이드 아크 주역이 바뀌어도 작품 주인공이 바뀌는 것은 아니다.
3. 후보의 work_protagonist_hint_count는 회차 모델의 noisy hint일 뿐이며 다수결 근거로 쓰지 마라.
4. episode_focal_count, lead_count, first_person_count, voice_count, coverage는 보조 증거다.
5. 빙의/환생/게임명/아바타/가명/페르소나는 동일인 신호일 수 있지만, 입력 후보가 이미 같은 cluster가 아니면 병합하지 마라.
6. 직책/호칭/관계/집단 라벨은 selection_eligible=true인 stable persona가 아니면 고르지 마라.
7. 대표 주인공 판정과 캐릭터챗 가능 인물 수집은 별도다. 선택되지 않은 주요 인물도 캐릭터챗 후보로 남을 수 있다.
8. 다른 후보가 주요 인물이어도, 한 후보가 작품 목표/서술 중심/지표에서 뚜렷하게 우세하면 RESOLVED로 고르라.
9. 상위 2~3명이 모두 selection_eligible=true이고, 작품 전체에서 행동/결정/서술 중심을 나눠 갖는 공동 주인공이면 work_protagonist_keys에 함께 넣고 reason_code="co_main_protagonists"로 반환하라.
10. 보호/구원/연애/임무의 대상, 히로인, 핵심 목표 인물이 강하게 등장해도 그 자체만으로 대표 주인공이 아니다. 행동/결정/서술의 주체를 우선하라.
11. duplicate_compaction.removed_cross_candidate_aliases는 오염 제거 기록이지 동일인 병합 근거가 아니다.
12. 후보 병합이 필요하거나 공개 가능한 이름이 없으면 UNRESOLVED를 반환하라.
13. 틀린 주인공 노출보다 미해결이 낫다. 확신이 없으면 UNRESOLVED다.
"""

EPISODE_CHARACTER_SIGNALS_TOOL_SCHEMA = {
    "name": EPISODE_CHARACTER_SIGNALS_TOOL_NAME,
    "description": "회차 요약에서 인물/관계/훅 구조화 신호를 JSON으로 반환한다.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "episode_no": {"type": "integer"},
            "mentioned_characters": {
                "type": "array",
                "maxItems": 6,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "display_name": {"type": "string"},
                        "aliases": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 6,
                        },
                        "is_protagonist": {"type": "boolean"},
                        "is_work_protagonist": {"type": "boolean"},
                        "is_episode_focal": {"type": "boolean"},
                        "is_first_person": {"type": "boolean"},
                        "narration_names": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 4,
                        },
                        "social_call_names": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 4,
                        },
                        "persona_names": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 4,
                        },
                        "real_names": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 4,
                        },
                        "entity_kind": {
                            "type": "string",
                            "enum": ["person", "stable_role", "collective", "other"],
                        },
                        "scene_weight": {
                            "type": "string",
                            "enum": ["high", "medium", "low"],
                        },
                        "role_in_episode": {
                            "type": "string",
                            "enum": ["lead", "counterpart", "support", "obstacle"],
                        },
                        "voice_mode": {
                            "type": "string",
                            "enum": ["dialogue", "monologue", "narration_only"],
                        },
                        "action_tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 4,
                        },
                        "affect_tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 4,
                        },
                        "relation_edges": {
                            "type": "array",
                            "maxItems": 5,
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "target_label": {"type": "string"},
                                    "relation_tag": {"type": "string"},
                                    "direction": {
                                        "type": "string",
                                        "enum": ["to_target", "from_target", "mutual"],
                                    },
                                },
                                "required": ["target_label", "relation_tag", "direction"],
                            },
                        },
                        "identity_claims": {
                            "type": "array",
                            "maxItems": 4,
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "target_label": {"type": "string"},
                                    "claim_type": {
                                        "type": "string",
                                        "enum": [
                                            "same_person_as",
                                            "alias_of",
                                            "real_name_of",
                                            "avatar_name_of",
                                            "game_name_of",
                                            "codename_of",
                                            "possessed_as",
                                            "self_reference_as",
                                            "title_of",
                                        ],
                                    },
                                    "evidence": {"type": "string"},
                                },
                                "required": ["target_label", "claim_type", "evidence"],
                            },
                        },
                    },
                    "required": [
                        "display_name",
                        "aliases",
                        "is_protagonist",
                        "is_work_protagonist",
                        "is_episode_focal",
                        "is_first_person",
                        "narration_names",
                        "social_call_names",
                        "persona_names",
                        "real_names",
                        "entity_kind",
                        "scene_weight",
                        "role_in_episode",
                        "voice_mode",
                        "action_tags",
                        "affect_tags",
                        "relation_edges",
                        "identity_claims",
                    ],
                },
            },
            "cliffhanger_hooks": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 3,
            },
        },
        "required": ["episode_no", "mentioned_characters", "cliffhanger_hooks"],
    },
}

WORK_PROTAGONIST_RESOLUTION_TOOL_SCHEMA = {
    "name": "submit_work_protagonist_resolution",
    "description": "작품 전체 주인공 후보 1명 또는 unresolved 판정을 JSON으로 반환한다.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "schema_version": {"type": "string"},
            "decision": {"type": "string", "enum": ["RESOLVED", "UNRESOLVED"]},
            "work_protagonist_key": {"type": ["string", "null"]},
            "work_protagonist_keys": {
                "type": "array",
                "maxItems": 3,
                "items": {"type": "string"},
            },
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "reason_code": {
                "type": "string",
                "enum": [
                    "single_clear",
                    "co_main_protagonists",
                    "pov_shift_same_protagonist",
                    "persona_rename_same_person",
                    "side_arc_not_protagonist",
                    "ambiguous_dual_lead",
                    "insufficient_evidence",
                ],
            },
            "rationale": {"type": "string"},
            "rejected": {
                "type": "array",
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "key": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["key", "reason"],
                },
            },
            "safety_flags": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "requires_identity_merge": {"type": "boolean"},
                    "selected_candidate_eligible": {"type": "boolean"},
                    "multiple_plausible_main_candidates": {"type": "boolean"},
                },
                "required": [
                    "requires_identity_merge",
                    "selected_candidate_eligible",
                    "multiple_plausible_main_candidates",
                ],
            },
        },
        "required": [
            "schema_version",
            "decision",
            "work_protagonist_key",
            "work_protagonist_keys",
            "confidence",
            "reason_code",
            "rationale",
            "rejected",
            "safety_flags",
        ],
    },
}


@dataclass(frozen=True)
class DeltaBuildScopePlan:
    product_id: int
    product_title: str
    touched_episode_ids: tuple[int, ...]
    touched_episode_nos: tuple[int, ...]
    episode_delta_reasons: tuple[tuple[int, int, str], ...]
    touched_range_scopes: tuple[tuple[str, int, int], ...]
    rebuild_product_summary: bool
    rebuild_character_inventory: bool
    rebuild_relation_inventory: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="스토리 에이전트 원문 컨텍스트 적재")
    parser.add_argument(
        "--build-mode",
        choices=("full", "delta"),
        default="full",
        help="full=기존 전체/대상 회차 기준 적재, delta=영향 scope 계획 산출",
    )
    parser.add_argument("--product-id", type=int, action="append", dest="product_ids", help="대상 작품 ID. 여러 번 지정 가능")
    parser.add_argument("--episode-id", type=int, action="append", dest="episode_ids", help="대상 회차 ID. 여러 번 지정 가능")
    parser.add_argument("--episode-no", type=int, action="append", dest="episode_nos", help="delta 대상 회차 번호. 여러 번 지정 가능")
    parser.add_argument("--limit", type=int, default=0, help="대상 제한 건수")
    parser.add_argument(
        "--max-delta-episodes",
        type=int,
        default=0,
        help="delta 모드에서 작품별 이번 실행에 처리할 최대 회차 수. 0은 제한 없음.",
    )
    parser.add_argument("--apply", action="store_true", help="실제 DB 적재 수행")
    parser.add_argument("--verbose", action="store_true", help="상세 로그 출력")
    parser.add_argument("--use-epub-fallback", action="store_true", help="episode_content가 비어 있으면 EPUB에서 임시 원문 추출")
    parser.add_argument(
        "--refresh-rp",
        action="store_true",
        help="delta 모드에서 캐릭터 RP 프로필/예시를 갱신. 기본 delta/cron에서는 비용 방지를 위해 생략.",
    )
    parser.add_argument(
        "--repair-character-assets",
        action="store_true",
        help="delta 모드에서 신규 회차가 없어도 캐릭터 scene/RP 결손을 제한적으로 복구.",
    )
    parser.add_argument(
        "--verification-json-path",
        type=str,
        default="",
        help="delta 검수 결과를 best-effort JSON으로 저장할 경로. 저장 실패가 배치를 실패시키진 않음.",
    )
    return parser.parse_args()


def db_connect(*, autocommit: bool = False):
    if not DB_USER or not DB_PASSWORD:
        raise RuntimeError("DB 접속 정보가 비어 있습니다. BATCH_DB_* 또는 app.const.settings를 확인하세요.")
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
        autocommit=autocommit,
        client_flag=CLIENT.MULTI_STATEMENTS,
        cursorclass=DictCursor,
    )


@contextmanager
def work_cursor(conn):
    conn.ping(reconnect=True)
    with conn.cursor() as cur:
        yield cur


@contextmanager
def product_lock_connection(product_id: int):
    lock_conn = db_connect(autocommit=True)
    acquired = False
    try:
        with lock_conn.cursor() as cur:
            acquired = acquire_product_lock(cur, product_id)
        yield lock_conn if acquired else None
    finally:
        if acquired:
            try:
                with lock_conn.cursor() as cur:
                    release_product_lock(cur, product_id)
            except Exception:
                pass
        lock_conn.close()


def acquire_product_lock(cur, product_id: int) -> bool:
    cur.execute("SELECT GET_LOCK(%s, 0) AS locked", (f"story-agent-context-product:{product_id}",))
    row = cur.fetchone() or {}
    return int(row.get("locked") or 0) == 1


def release_product_lock(cur, product_id: int) -> None:
    cur.execute("SELECT RELEASE_LOCK(%s)", (f"story-agent-context-product:{product_id}",))


def build_target_query(args: argparse.Namespace, use_epub_fallback: bool) -> tuple[str, list[object]]:
    where = [
        "p.price_type IN ('free', 'paid')",
        "p.status_code = 'ongoing'",
        "pe.use_yn = 'Y'",
        "pe.open_yn = 'Y'",
        "p.open_yn = 'Y'",
        "COALESCE(p.blind_yn, 'N') = 'N'",
        "COALESCE(p.ai_content_service_enabled_yn, 'N') = 'Y'",
        "COALESCE(sacp.context_status, 'pending') <> 'disabled'",
    ]
    params: list[object] = []

    if args.product_ids:
        placeholders = ", ".join(["%s"] * len(args.product_ids))
        where.append(f"p.product_id IN ({placeholders})")
        params.extend(args.product_ids)

    if args.episode_ids:
        placeholders = ", ".join(["%s"] * len(args.episode_ids))
        where.append(f"pe.episode_id IN ({placeholders})")
        params.extend(args.episode_ids)

    if args.episode_nos:
        placeholders = ", ".join(["%s"] * len(args.episode_nos))
        where.append(f"pe.episode_no IN ({placeholders})")
        params.extend(args.episode_nos)

    where_sql = " AND ".join(where)
    limit_sql = f" LIMIT {int(args.limit)}" if args.limit and args.limit > 0 else ""

    file_join_sql = ""
    file_select_sql = "NULL AS file_name"
    if use_epub_fallback:
        file_join_sql = """
        LEFT JOIN tb_common_file cf
          ON cf.file_group_id = pe.epub_file_id
         AND cf.group_type = 'epub'
         AND cf.use_yn = 'Y'
        LEFT JOIN tb_common_file_item cfi
          ON cfi.file_group_id = cf.file_group_id
         AND cfi.use_yn = 'Y'
        """
        file_select_sql = "cfi.file_name"

    query = f"""
        SELECT
            p.product_id,
            p.title,
            pe.episode_id,
            pe.episode_no,
            pe.episode_title,
            pe.episode_content,
            pe.episode_text_count,
            pe.epub_file_id,
            {file_select_sql}
        FROM tb_product p
        JOIN tb_product_episode pe
          ON pe.product_id = p.product_id
        LEFT JOIN tb_story_agent_context_product sacp
          ON sacp.product_id = p.product_id
        {file_join_sql}
        WHERE {where_sql}
        ORDER BY p.product_id ASC, pe.episode_no ASC
        {limit_sql}
    """
    return query, params


def normalize_episode_html(html_content: str) -> str:
    soup = BeautifulSoup(html_content or "", "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    text = soup.get_text(separator="\n")
    text = text.replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    paragraphs: list[str] = []
    blank_open = False
    for line in lines:
        if not line:
            if paragraphs and not blank_open:
                paragraphs.append("")
                blank_open = True
            continue
        paragraphs.append(line)
        blank_open = False
    normalized = "\n".join(paragraphs).strip()
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def split_long_paragraph(paragraph: str) -> list[str]:
    if len(paragraph) <= MAX_CHUNK_LEN:
        return [paragraph]

    sentences = [item.strip() for item in SENTENCE_SPLIT_RE.split(paragraph) if item.strip()]
    if len(sentences) <= 1:
        return [paragraph[i:i + MAX_CHUNK_LEN] for i in range(0, len(paragraph), MAX_CHUNK_LEN)]

    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = f"{current} {sentence}".strip() if current else sentence
        if current and len(candidate) > MAX_CHUNK_LEN:
            chunks.append(current)
            current = sentence
            continue
        current = candidate
    if current:
        chunks.append(current)
    return chunks


def build_chunks(normalized_text: str) -> list[dict[str, object]]:
    if not normalized_text:
        return []

    units: list[str] = []
    for paragraph in normalized_text.split("\n\n"):
        cleaned = paragraph.strip()
        if not cleaned:
            continue
        units.extend(split_long_paragraph(cleaned))

    chunks: list[dict[str, object]] = []
    buffer = ""
    for unit in units:
        candidate = f"{buffer}\n\n{unit}".strip() if buffer else unit
        if buffer and len(candidate) > TARGET_CHUNK_LEN:
            chunks.append({"text": buffer})
            buffer = unit
            continue
        buffer = candidate
    if buffer:
        chunks.append({"text": buffer})

    offset = 0
    for idx, chunk in enumerate(chunks, start=1):
        text = str(chunk["text"])
        start = normalized_text.find(text, offset)
        if start < 0:
            start = offset
        end = start + len(text)
        chunk["chunk_no"] = idx
        chunk["char_start"] = start
        chunk["char_end"] = end
        chunk["text_hash"] = sha256_text(text)
        offset = end
    return chunks


def extract_summary_sentences(normalized_text: str, limit: int = 3) -> list[str]:
    sentences: list[str] = []
    for paragraph in normalized_text.split("\n\n"):
        cleaned = paragraph.strip()
        if not cleaned:
            continue
        candidates = [item.strip() for item in SENTENCE_SPLIT_RE.split(cleaned) if item.strip()]
        if not candidates:
            candidates = [cleaned]
        for candidate in candidates:
            if candidate in sentences:
                continue
            sentences.append(candidate)
            if len(sentences) >= limit:
                return sentences
    return sentences[:limit]


def extract_keywords(title: str, normalized_text: str, limit: int = 8) -> list[str]:
    counts: dict[str, int] = {}
    source = f"{title}\n{normalized_text[:3000]}"
    for token in KEYWORD_RE.findall(source):
        normalized = token.strip()
        if len(normalized) < 2:
            continue
        if normalized in KEYWORD_STOPWORDS:
            continue
        counts[normalized] = counts.get(normalized, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [item[0] for item in ranked[:limit]]


def build_episode_summary_header(row: dict) -> str:
    raw_title = str(row.get("episode_title") or "").strip()
    matched = EPISODE_TITLE_LABEL_RE.match(raw_title)
    if matched:
        title_label = matched.group("label")
        title_text = matched.group("title").strip(" .:-") or raw_title
        return f"[{title_label}] {title_text}"

    episode_no = int(row.get("episode_no") or 0)
    title_text = raw_title or "요약"
    return f"[{episode_no}화] {title_text}"


def build_episode_summary_text(row: dict, normalized_text: str) -> str:
    episode_label = build_episode_summary_header(row)
    sentences = extract_summary_sentences(normalized_text)
    keywords = extract_keywords(str(row.get("episode_title") or ""), normalized_text)

    bullet_lines = [f"- {sentence}" for sentence in sentences[:3]]
    if not bullet_lines:
        bullet_lines = ["- 요약 가능한 문장을 찾지 못했습니다."]
    keyword_line = f"- 키워드: {', '.join(keywords)}" if keywords else "- 키워드:"
    return "\n".join([episode_label, *bullet_lines, keyword_line]).strip()


def build_episode_summary_user_prompt(row: dict, normalized_text: str) -> str:
    header = build_episode_summary_header(row)
    title = str(row.get("title") or "").strip()
    episode_title = str(row.get("episode_title") or "").strip()
    name_candidates = extract_episode_summary_name_candidates(normalized_text)
    name_candidate_line = ", ".join(name_candidates) if name_candidates else "없음"
    return (
        "다음 회차 원문을 검색용 summary_text로 변환하라.\n"
        "첫 줄은 반드시 아래 문구를 그대로 사용하라.\n"
        f"{header}\n\n"
        "반드시 지킬 것:\n"
        "- 본문은 핵심 사건만 남기고 시간순 나열/세부 로그는 줄이기\n"
        "- 각 줄은 구체 사건 중심으로 작성\n"
        "- 마지막 줄은 반드시 \"핵심:\"으로 시작\n"
        "- 핵심 항목은 정확히 6~8개\n"
        "- 추상 표현 대신 누가 무엇을 했고 어떤 결과가 났는지 적기\n"
        "- 고유명사, 능력명, 수치, 제약, 장비명은 원문 그대로 최대한 보존\n\n"
        f"작품명: {title}\n"
        f"회차 제목: {episode_title}\n"
        f"등장 인물/고유 호칭 후보(soft hint): {name_candidate_line}\n"
        f"원문:\n{normalized_text[:EPISODE_SUMMARY_MAX_INPUT_CHARS]}"
    )


def extract_episode_summary_name_candidates(normalized_text: str, limit: int = 6) -> list[str]:
    text = str(normalized_text or "")
    if not text:
        return []

    counts: Counter[str] = Counter()
    for token in NAME_WITH_PARTICLE_RE.findall(text):
        normalized = str(token or "").strip()
        if len(normalized) < 2 or len(normalized) > 8:
            continue
        if normalized in CHARACTER_STOPWORDS:
            continue
        if normalized in {"주인공", "후배", "아이", "오빠", "언니", "남자", "여자"}:
            continue
        counts[normalized] += 1

    for match in re.findall(r'["“]([가-힣A-Za-z0-9]{2,8})(?:아|야)[!?.…~,"\']*', text):
        normalized = str(match or "").strip()
        if normalized and normalized not in CHARACTER_STOPWORDS:
            counts[normalized] += 1

    ranked = sorted(
        counts.items(),
        key=lambda item: (-item[1], len(item[0]), item[0]),
    )
    return [item[0] for item in ranked[:limit]]


def extract_openrouter_message_text(payload: dict) -> str:
    message = (payload.get("choices") or [{}])[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = str(item.get("text") or "").strip()
            else:
                text = str(item).strip()
            if text:
                parts.append(text)
        return "\n".join(parts).strip()
    return str(content or "").strip()


def extract_anthropic_message_text(payload: dict) -> str:
    content = payload.get("content") or []
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "") != "text":
            continue
        text_value = str(item.get("text") or "").strip()
        if text_value:
            parts.append(text_value)
    return "\n".join(parts).strip()


def extract_anthropic_tool_input(payload: dict, *, tool_name: str) -> dict | None:
    for item in list(payload.get("content") or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "").strip() != "tool_use":
            continue
        if str(item.get("name") or "").strip() != tool_name:
            continue
        tool_input = item.get("input")
        if isinstance(tool_input, dict):
            return tool_input
    return None


def split_csv_values(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def require_paid_rp_openrouter_model() -> str:
    model = str(RP_OPENROUTER_MODEL or "").strip()
    if not model:
        raise RuntimeError("STORY_AGENT_RP_OPENROUTER_MODEL is empty")
    if model.lower().endswith(":free"):
        raise RuntimeError("STORY_AGENT_RP_OPENROUTER_MODEL must not use :free")
    return model


def require_paid_character_signals_openrouter_model() -> str:
    model = str(EPISODE_CHARACTER_SIGNALS_OPENROUTER_MODEL or "").strip()
    if not model:
        raise RuntimeError("STORY_AGENT_CHARACTER_SIGNALS_OPENROUTER_MODEL is empty")
    if model.lower().endswith(":free"):
        raise RuntimeError("STORY_AGENT_CHARACTER_SIGNALS_OPENROUTER_MODEL must not use :free")
    return model


def require_paid_episode_scene_extraction_openrouter_model() -> str:
    model = str(EPISODE_SCENE_EXTRACTION_OPENROUTER_MODEL or "").strip()
    if not model:
        raise RuntimeError("STORY_AGENT_SCENE_EXTRACTION_OPENROUTER_MODEL is empty")
    if model.lower().endswith(":free"):
        raise RuntimeError("STORY_AGENT_SCENE_EXTRACTION_OPENROUTER_MODEL must not use :free")
    return model


def build_rp_openrouter_payload(
    *,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    model: str | None = None,
) -> dict[str, object]:
    selected_model = str(model or "").strip() or require_paid_rp_openrouter_model()
    if selected_model.lower().endswith(":free"):
        raise RuntimeError("OpenRouter model must not use :free")
    payload: dict[str, object] = {
        "model": selected_model,
        "temperature": 0.0,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        "reasoning": {"effort": "none", "exclude": True},
        "messages": [
            {"role": "system", "content": f"{system_prompt}\n\n반드시 유효한 JSON object만 반환하라."},
            {"role": "user", "content": user_prompt},
        ],
    }
    provider_only = split_csv_values(RP_OPENROUTER_PROVIDER_ONLY)
    if provider_only:
        payload["provider"] = {
            "only": provider_only,
            "order": provider_only,
            "allow_fallbacks": len(provider_only) > 1,
        }
    return payload


def build_character_signals_openrouter_payload(*, user_prompt: str) -> dict[str, object]:
    payload: dict[str, object] = {
        "model": require_paid_character_signals_openrouter_model(),
        "temperature": 0.0,
        "max_tokens": EPISODE_CHARACTER_SIGNALS_MAX_OUTPUT_TOKENS,
        "response_format": {"type": "json_object"},
        "reasoning": {"effort": "none", "exclude": True},
        "messages": [
            {
                "role": "system",
                "content": f"{EPISODE_CHARACTER_SIGNALS_PROMPT}\n\n반드시 유효한 JSON object만 반환하라.",
            },
            {"role": "user", "content": user_prompt},
        ],
    }
    provider_only = split_csv_values(DEEPSEEK_OPENROUTER_PROVIDER_ONLY)
    if provider_only:
        payload["provider"] = {
            "only": provider_only,
            "order": provider_only,
            "allow_fallbacks": len(provider_only) > 1,
        }
    return payload


def build_episode_scene_extraction_openrouter_payload(*, user_prompt: str) -> dict[str, object]:
    payload: dict[str, object] = {
        "model": require_paid_episode_scene_extraction_openrouter_model(),
        "temperature": 0.0,
        "max_tokens": EPISODE_SCENE_EXTRACTION_MAX_OUTPUT_TOKENS,
        "response_format": {"type": "json_object"},
        "reasoning": {"effort": "none", "exclude": True},
        "messages": [
            {
                "role": "system",
                "content": f"{EPISODE_SCENE_EXTRACTION_SYSTEM}\n\n반드시 유효한 JSON object만 반환하라.",
            },
            {"role": "user", "content": user_prompt},
        ],
    }
    provider_only = split_csv_values(DEEPSEEK_OPENROUTER_PROVIDER_ONLY)
    if provider_only:
        payload["provider"] = {
            "only": provider_only,
            "order": provider_only,
            "allow_fallbacks": len(provider_only) > 1,
        }
    return payload


async def request_rp_openrouter_json_payload(
    client: AsyncClient,
    *,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    title: str,
    model: str | None = None,
    timeout_seconds: float | None = None,
) -> dict | None:
    request_timeout_seconds = timeout_seconds or RP_OPENROUTER_TIMEOUT_SECONDS
    response = await asyncio.wait_for(
        client.post(
            f"{OPENROUTER_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "X-Title": title,
            },
            json=build_rp_openrouter_payload(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens,
                model=model,
            ),
            timeout=request_timeout_seconds,
        ),
        timeout=request_timeout_seconds,
    )
    response.raise_for_status()
    return extract_json_object(extract_openrouter_message_text(response.json()))


async def request_episode_scene_extraction_openrouter_json_payload(
    client: AsyncClient,
    *,
    user_prompt: str,
) -> dict | None:
    response = await asyncio.wait_for(
        client.post(
            f"{OPENROUTER_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "X-Title": "LikeNovel Story Agent Episode Scene Extraction Batch",
            },
            json=build_episode_scene_extraction_openrouter_payload(user_prompt=user_prompt),
        ),
        timeout=EPISODE_SCENE_EXTRACTION_OPENROUTER_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return extract_json_object(extract_openrouter_message_text(response.json()))


class EpisodeCharacterSignalsParseError(ValueError):
    def __init__(
        self,
        *,
        episode_no: int,
        model: str,
        request_id: str,
        json_parse_ok: bool,
        line_parse_ok: bool,
        char_count: int,
        rel_count: int,
        hook_count: int,
        raw_sha256: str,
        raw_preview: str,
    ) -> None:
        super().__init__(f"episode_character_signals returned no parseable structured output: episode_no={episode_no}")
        self.episode_no = episode_no
        self.model = model
        self.request_id = request_id
        self.json_parse_ok = json_parse_ok
        self.line_parse_ok = line_parse_ok
        self.char_count = char_count
        self.rel_count = rel_count
        self.hook_count = hook_count
        self.raw_sha256 = raw_sha256
        self.raw_preview = raw_preview


def build_episode_character_signals_parse_diagnostics(raw_text: str) -> dict[str, object]:
    raw = str(raw_text or "")
    json_payload = extract_json_object(raw)
    line_payload = parse_episode_character_signals_structured_text(raw)
    mentioned_characters = list((line_payload or {}).get("mentioned_characters") or [])
    relation_count = sum(len(list((item or {}).get("relation_edges") or [])) for item in mentioned_characters)
    cliffhanger_hooks = list((line_payload or {}).get("cliffhanger_hooks") or [])
    preview = raw.replace("\r", "\\r").replace("\n", "\\n")
    if len(preview) > 500:
        preview = f"{preview[:500]}..."
    return {
        "json_parse_ok": bool(json_payload),
        "line_parse_ok": bool(line_payload),
        "char_count": len(mentioned_characters),
        "rel_count": relation_count,
        "hook_count": len(cliffhanger_hooks),
        "raw_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest() if raw else "",
        "raw_preview": preview,
    }


def build_anthropic_reasoning_options(model: str) -> dict[str, object]:
    normalized_model = str(model or "").strip()
    if normalized_model not in {"claude-sonnet-4-6", "claude-opus-4-6"}:
        return {}

    thinking_payload: dict[str, object] = {"type": "adaptive"}
    if RP_REASONING_THINKING_DISPLAY in {"summarized", "omitted"}:
        thinking_payload["display"] = RP_REASONING_THINKING_DISPLAY

    effort_value = RP_REASONING_EFFORT if RP_REASONING_EFFORT in {"low", "medium", "high", "max"} else "medium"
    return {
        "thinking": thinking_payload,
        "output_config": {"effort": effort_value},
    }


def build_episode_summary_core_line(title_text: str, normalized_text: str, max_items: int = 8) -> str:
    keywords = extract_keywords(title_text, normalized_text)[:max_items]
    return f"핵심:{', '.join(keywords)}" if keywords else "핵심:"


def repair_episode_summary_text(
    text: str,
    *,
    expected_header: str,
    row: dict,
    normalized_text: str,
) -> str:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw).strip()

    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if not lines:
        return ""

    expected_match = EPISODE_SUMMARY_FIRST_LINE_RE.match(expected_header)
    expected_label = str(expected_match.group("label") or "").strip() if expected_match else ""

    repaired_lines: list[str] = []
    first_match = EPISODE_SUMMARY_FIRST_LINE_RE.match(lines[0])
    if not first_match:
        repaired_lines.append(expected_header)
        repaired_lines.extend(lines)
    else:
        actual_label = str(first_match.group("label") or "").strip()
        if expected_label and actual_label != expected_label:
            repaired_lines.append(expected_header)
            repaired_lines.extend(lines[1:])
        else:
            repaired_lines = lines[:]

    core_index = next((idx for idx, line in enumerate(repaired_lines) if line.startswith("핵심:")), -1)
    if core_index == -1:
        repaired_lines.append(build_episode_summary_core_line(str(row.get("episode_title") or ""), normalized_text))
    else:
        anchors = [item.strip() for item in repaired_lines[core_index].replace("핵심:", "", 1).split(",") if item.strip()]
        if not (6 <= len(anchors) <= 8):
            repaired_lines[core_index] = build_episode_summary_core_line(str(row.get("episode_title") or ""), normalized_text)

    return "\n".join(line for line in repaired_lines if line.strip()).strip()


def validate_episode_summary_text(text: str, *, expected_header: str) -> tuple[bool, list[str], bool]:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    issues: list[str] = []
    if not lines:
        return False, ["empty"], True

    first_match = EPISODE_SUMMARY_FIRST_LINE_RE.match(lines[0])
    expected_match = EPISODE_SUMMARY_FIRST_LINE_RE.match(expected_header)
    if not first_match:
        issues.append("invalid_first_line")
    elif not expected_match:
        issues.append("invalid_expected_header")
    else:
        actual_label = str(first_match.group("label") or "").strip()
        expected_label = str(expected_match.group("label") or "").strip()
        if actual_label != expected_label:
            issues.append("header_label_mismatch")

    core_line = next((line for line in reversed(lines) if line.startswith("핵심:")), "")
    if not core_line:
        issues.append("missing_core_line")

    body = [line for line in lines[1:] if line and not line.startswith("핵심:")]
    if len(body) < 1:
        issues.append("missing_body")

    if core_line:
        anchors = [item.strip() for item in core_line.replace("핵심:", "", 1).split(",") if item.strip()]
        if not (6 <= len(anchors) <= 8):
            issues.append("invalid_anchor_count")

    critical_issue_set = {"empty", "invalid_first_line", "missing_core_line", "missing_body"}
    is_critical = any(issue in critical_issue_set for issue in issues)
    return len(issues) == 0, issues, is_critical


def validate_episode_summary_semantics(
    text: str,
    *,
    soft_name_candidates: list[str],
) -> tuple[list[str], bool]:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    if len(lines) < 2:
        return [], False

    body_lines = [line for line in lines[1:] if line and not line.startswith("핵심:")]
    core_line = next((line for line in reversed(lines) if line.startswith("핵심:")), "")
    body_text = "\n".join(body_lines)
    candidate_set = [candidate for candidate in soft_name_candidates if candidate]
    if len(candidate_set) < 2:
        return [], False

    issues: list[str] = []
    body_anchor_count = sum(1 for candidate in candidate_set if candidate in body_text)
    core_anchor_count = sum(1 for candidate in candidate_set if candidate in core_line)
    generic_role_hits = sum(body_text.count(token) for token in ("주인공", "후배", "아이", "남자", "여자"))

    if body_anchor_count == 0:
        issues.append("missing_name_anchor_in_body")
    if core_line and core_anchor_count == 0:
        issues.append("missing_name_anchor_in_core")
    if generic_role_hits >= 3 and body_anchor_count <= 1:
        issues.append("role_only_body")

    return issues, bool(issues)


async def request_episode_summary_text(
    client: AsyncClient,
    *,
    row: dict,
    normalized_text: str,
) -> str:
    response = await client.post(
        f"{OPENROUTER_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "X-Title": "LikeNovel Story Agent Episode Summary Batch",
        },
        json={
            "model": EPISODE_SUMMARY_MODEL,
            "temperature": EPISODE_SUMMARY_TEMPERATURE,
            "max_completion_tokens": EPISODE_SUMMARY_MAX_OUTPUT_TOKENS,
            "messages": [
                {"role": "system", "content": EPISODE_SUMMARY_SYSTEM_PROMPT},
                {"role": "user", "content": build_episode_summary_user_prompt(row, normalized_text)},
            ],
        },
    )
    response.raise_for_status()
    return extract_openrouter_message_text(response.json())


def is_openrouter_payment_required_error(exc: BaseException) -> bool:
    return isinstance(exc, HTTPStatusError) and getattr(exc.response, "status_code", None) == 402


def is_anthropic_billing_error(exc: BaseException) -> bool:
    if not isinstance(exc, HTTPStatusError):
        return False
    status_code = int(getattr(exc.response, "status_code", 0) or 0)
    if status_code not in {400, 402, 429}:
        return False
    body = str(getattr(exc.response, "text", "") or "").lower()
    return "credit balance" in body or "billing" in body or "purchase credits" in body


async def assert_storyctx_openrouter_apply_ready(client: AsyncClient | None) -> None:
    if client is None or not OPENROUTER_API_KEY or not (EPISODE_SUMMARY_MODEL or RP_OPENROUTER_MODEL):
        return
    model = EPISODE_SUMMARY_MODEL or RP_OPENROUTER_MODEL
    try:
        response = await client.post(
            f"{OPENROUTER_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "X-Title": "LikeNovel Story Agent OpenRouter Preflight",
            },
            json={
                "model": model,
                "temperature": 0.0,
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "ping"}],
            },
        )
        response.raise_for_status()
    except HTTPStatusError as exc:
        if is_openrouter_payment_required_error(exc):
            raise RuntimeError("OpenRouter preflight failed: 402 Payment Required") from exc
        raise


async def assert_storyctx_anthropic_apply_ready(client: AsyncClient | None) -> None:
    if client is None or not settings.ANTHROPIC_API_KEY or not RP_REASONING_MODEL:
        return
    try:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": RP_REASONING_MODEL,
                "max_tokens": 8,
                "messages": [{"role": "user", "content": "ping"}],
            },
        )
        response.raise_for_status()
    except HTTPStatusError as exc:
        if is_anthropic_billing_error(exc):
            raise RuntimeError("Anthropic preflight failed: billing or credit unavailable") from exc
        raise


async def assert_storyctx_apply_providers_ready(client: AsyncClient | None) -> None:
    await assert_storyctx_openrouter_apply_ready(client)
    await assert_storyctx_anthropic_apply_ready(client)


async def generate_episode_summary_text(
    *,
    client: AsyncClient | None,
    row: dict,
    normalized_text: str,
    verbose: bool = False,
) -> tuple[str, dict[str, object]]:
    fallback_text = build_episode_summary_text(row=row, normalized_text=normalized_text)
    fallback_meta = {
        "used_llm": False,
        "retry_count": 0,
        "fallback_used": True,
        "fallback_reason": "llm_unavailable",
        "repaired_output": False,
    }
    if client is None or not OPENROUTER_API_KEY or not EPISODE_SUMMARY_MODEL:
        return fallback_text, fallback_meta

    expected_header = build_episode_summary_header(row)
    soft_name_candidates = extract_episode_summary_name_candidates(normalized_text)
    last_candidate = ""
    last_issues: list[str] = []
    for attempt in range(2):
        try:
            summary_text = await request_episode_summary_text(
                client,
                row=row,
                normalized_text=normalized_text,
            )
        except (HTTPStatusError, RequestError, ValueError) as exc:
            if verbose:
                print(
                    f"[summary-llm-error] product_id={row['product_id']} episode_id={row['episode_id']} "
                    f"attempt={attempt + 1} error={str(exc)[:200]}"
                )
            continue

        repaired_text = repair_episode_summary_text(
            summary_text,
            expected_header=expected_header,
            row=row,
            normalized_text=normalized_text,
        )
        valid, issues, is_critical = validate_episode_summary_text(repaired_text, expected_header=expected_header)
        semantic_issues, has_semantic_issue = validate_episode_summary_semantics(
            repaired_text,
            soft_name_candidates=soft_name_candidates,
        )
        if has_semantic_issue:
            issues = [*issues, *semantic_issues]
        last_candidate = repaired_text
        last_issues = issues
        if valid and not has_semantic_issue:
            return repaired_text, {
                "used_llm": True,
                "retry_count": attempt,
                "fallback_used": False,
                "fallback_reason": "",
                "repaired_output": repaired_text != str(summary_text or "").strip(),
            }

        if verbose:
            print(
                f"[summary-llm-invalid] product_id={row['product_id']} episode_id={row['episode_id']} "
                f"attempt={attempt + 1} issues={','.join(issues)} critical={is_critical}"
            )

        if not is_critical and not has_semantic_issue and repaired_text:
            return repaired_text, {
                "used_llm": True,
                "retry_count": attempt,
                "fallback_used": False,
                "fallback_reason": "",
                "repaired_output": True,
            }

    if last_candidate:
        return last_candidate, {
            "used_llm": True,
            "retry_count": 1,
            "fallback_used": False,
            "fallback_reason": "stored_noncritical_invalid",
            "repaired_output": True,
            "quality_issues": ",".join(last_issues),
        }

    return fallback_text, {
        "used_llm": False,
        "retry_count": 1,
        "fallback_used": True,
        "fallback_reason": "validation_failed",
        "repaired_output": False,
    }


def build_summary_source_hash(source_hash: str, episode_title: str) -> str:
    normalized_title = (episode_title or "").strip()
    return sha256_text(f"{EPISODE_SUMMARY_FORMAT_VERSION}:{source_hash}:{normalized_title}")


def build_compound_summary_source_hash(format_version: str, components: list[str]) -> str:
    normalized_components = [component.strip() for component in components if component and component.strip()]
    return sha256_text(f"{format_version}:{'|'.join(normalized_components)}")


def build_rp_reasoning_signature() -> str:
    if RP_REASONING_MODEL:
        return "|".join(
            [
                "anthropic",
                RP_REASONING_MODEL,
                RP_REASONING_EFFORT,
                RP_REASONING_THINKING_DISPLAY,
            ]
        )
    if not OPENROUTER_API_KEY or not EPISODE_CHARACTER_SIGNALS_OPENROUTER_MODEL:
        return "none"
    return "|".join(
        [
            "openrouter",
            require_paid_character_signals_openrouter_model(),
            "reasoning:none",
        ]
    )


def build_rp_profile_model_signature() -> str:
    return "|".join(
        [
            require_paid_rp_openrouter_model(),
            RP_OPENROUTER_PROVIDER_ONLY,
            f"min_examples:{RP_PROFILE_MIN_EXAMPLE_TEXTS}",
            "reasoning:none",
        ]
    )


def _log_value(value: object) -> str:
    text = str(value or "").strip()
    return text if text else "none"


def is_episode_character_signals_provider_available() -> bool:
    return bool(
        (settings.ANTHROPIC_API_KEY and RP_REASONING_MODEL)
        or (OPENROUTER_API_KEY and EPISODE_CHARACTER_SIGNALS_OPENROUTER_MODEL)
    )


def build_storyctx_provider_summary_line() -> str:
    episode_summary_provider = "openrouter" if OPENROUTER_API_KEY and EPISODE_SUMMARY_MODEL else "local_fallback"
    rp_openrouter_provider = "openrouter" if OPENROUTER_API_KEY and RP_OPENROUTER_MODEL else "disabled"
    if settings.ANTHROPIC_API_KEY and RP_REASONING_MODEL:
        signal_provider = "anthropic"
        signal_model = RP_REASONING_MODEL
        if OPENROUTER_API_KEY and EPISODE_CHARACTER_SIGNALS_OPENROUTER_MODEL:
            signal_fallback_provider = "openrouter"
            signal_fallback_model = EPISODE_CHARACTER_SIGNALS_OPENROUTER_MODEL
        else:
            signal_fallback_provider = "none"
            signal_fallback_model = "none"
    elif OPENROUTER_API_KEY and EPISODE_CHARACTER_SIGNALS_OPENROUTER_MODEL:
        signal_provider = "openrouter"
        signal_model = EPISODE_CHARACTER_SIGNALS_OPENROUTER_MODEL
        signal_fallback_provider = "none"
        signal_fallback_model = "none"
    else:
        signal_provider = "unavailable"
        signal_model = "none"
        signal_fallback_provider = "none"
        signal_fallback_model = "none"

    return (
        "storyctx-provider "
        f"episode_summary_provider={episode_summary_provider} "
        f"episode_summary_model={_log_value(EPISODE_SUMMARY_MODEL)} "
        f"episode_character_signals_provider={signal_provider} "
        f"episode_character_signals_model={_log_value(signal_model)} "
        f"episode_character_signals_fallback_provider={signal_fallback_provider} "
        f"episode_character_signals_fallback_model={_log_value(signal_fallback_model)} "
        f"rp_character_plan_provider={rp_openrouter_provider} "
        f"rp_character_plan_model={_log_value(RP_OPENROUTER_MODEL)} "
        f"rp_profile_provider={rp_openrouter_provider} "
        f"rp_profile_model={_log_value(RP_OPENROUTER_MODEL)} "
        f"rp_openrouter_provider_only={_log_value(RP_OPENROUTER_PROVIDER_ONLY)}"
    )


def build_summary_product_ids(results: dict[str, object]) -> str:
    product_ids = [
        str(product.get("product_id"))
        for product in list(results.get("products") or [])[:20]
        if isinstance(product, dict) and product.get("product_id") is not None
    ]
    return ",".join(product_ids) if product_ids else "none"


def parse_summary_text(summary_text: str) -> dict[str, object]:
    lines = [line.strip() for line in (summary_text or "").splitlines() if line.strip()]
    header = lines[0] if lines else ""
    bullets: list[str] = []
    keywords: list[str] = []

    if len(lines) >= 2 and lines[-1].startswith("핵심:"):
        keyword_text = lines[-1].replace("핵심:", "", 1).strip()
        keywords = [item.strip() for item in keyword_text.split(",") if item.strip()]
        bullets = [line.strip() for line in lines[1:-1] if line.strip()]
        return {
            "header": header,
            "bullets": bullets,
            "keywords": keywords,
        }

    for line in lines[1:]:
        if line.startswith("- 키워드:"):
            keyword_text = line.replace("- 키워드:", "", 1).strip()
            keywords = [item.strip() for item in keyword_text.split(",") if item.strip()]
            continue
        if line.startswith("- "):
            bullets.append(line[2:].strip())
    return {
        "header": header,
        "bullets": bullets,
        "keywords": keywords,
    }


def fetch_active_summary_rows(cur, product_id: int, summary_type: str) -> list[dict]:
    cur.execute(
        """
        SELECT summary_id, scope_key, episode_from, episode_to, source_hash, summary_text
          FROM tb_story_agent_context_summary
         WHERE product_id = %s
           AND summary_type = %s
           AND is_active = 'Y'
         ORDER BY COALESCE(episode_from, 0) ASC, summary_id ASC
        """,
        (product_id, summary_type),
    )
    return list(cur.fetchall())


def fetch_active_summary_rows_for_episode_nos(
    cur,
    *,
    product_id: int,
    summary_type: str,
    episode_nos: Iterable[int],
) -> list[dict]:
    normalized_episode_nos = sorted(set(int(value) for value in episode_nos if int(value) > 0))
    if not normalized_episode_nos:
        return []

    placeholders = ", ".join(["%s"] * len(normalized_episode_nos))
    cur.execute(
        f"""
        SELECT summary_id, scope_key, episode_from, episode_to, source_hash, summary_text
          FROM tb_story_agent_context_summary
         WHERE product_id = %s
           AND summary_type = %s
           AND is_active = 'Y'
           AND episode_from IN ({placeholders})
         ORDER BY COALESCE(episode_from, 0) ASC, summary_id ASC
        """,
        [product_id, summary_type, *normalized_episode_nos],
    )
    return list(cur.fetchall())


def pick_spread_rows(rows: list[dict], limit: int) -> list[dict]:
    if len(rows) <= limit:
        return rows
    if limit <= 1:
        return [rows[0]]
    last_index = len(rows) - 1
    indexes: list[int] = []
    for step in range(limit):
        idx = round((last_index * step) / (limit - 1))
        if idx not in indexes:
            indexes.append(idx)
    return [rows[idx] for idx in indexes]


def build_work_protagonist_episode_summary_evidence(
    episode_summary_rows: list[dict],
    *,
    limit: int = 20,
) -> list[dict[str, object]]:
    evidence_rows: list[dict[str, object]] = []
    for row in pick_spread_rows(list(episode_summary_rows or []), limit):
        summary_text = str(row.get("summary_text") or "").strip()
        if not summary_text:
            continue
        parsed = parse_summary_text(summary_text)
        episode_no = int(row.get("episode_from") or row.get("episode_to") or 0)
        evidence_rows.append(
            {
                "episode_no": episode_no,
                "header": str(parsed.get("header") or "")[:120],
                "bullets": [str(item).strip()[:180] for item in list(parsed.get("bullets") or [])[:3] if str(item).strip()],
                "keywords": [str(item).strip()[:40] for item in list(parsed.get("keywords") or [])[:10] if str(item).strip()],
            }
        )
    return evidence_rows


def build_range_scope_keys(episode_nos: list[int]) -> list[tuple[str, int, int]]:
    if not episode_nos:
        return []
    max_episode_no = max(episode_nos)
    scopes: list[tuple[str, int, int]] = []
    start = 1
    while start <= max_episode_no:
        end = start + RANGE_SUMMARY_EPISODE_SPAN - 1
        scopes.append((f"range:{start}-{end}", start, end))
        start = end + 1
    return scopes


def select_touched_range_scopes(episode_nos: list[int]) -> list[tuple[str, int, int]]:
    touched_episode_nos = sorted(set(int(value) for value in episode_nos if int(value) > 0))
    if not touched_episode_nos:
        return []

    all_scopes = build_range_scope_keys(touched_episode_nos)
    touched_scopes: list[tuple[str, int, int]] = []
    for scope_key, start_episode, end_episode in all_scopes:
        if any(start_episode <= episode_no <= end_episode for episode_no in touched_episode_nos):
            touched_scopes.append((scope_key, start_episode, end_episode))
    return touched_scopes


def validate_delta_args(args: argparse.Namespace) -> None:
    if args.build_mode != "delta":
        if bool(getattr(args, "repair_character_assets", False)):
            raise ValueError("--repair-character-assets는 --build-mode delta에서만 사용할 수 있습니다.")
        return
    if args.limit:
        raise ValueError("--build-mode delta 에서는 --limit를 지원하지 않습니다.")
    if not args.product_ids:
        raise ValueError("--build-mode delta 에서는 --product-id가 필수입니다.")
    if args.max_delta_episodes < 0:
        raise ValueError("--max-delta-episodes 는 0 이상이어야 합니다.")


def should_refresh_delta_rp(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "refresh_rp", False))


def get_openrouter_retry_delay_seconds(exc: Exception) -> float | None:
    if not isinstance(exc, HTTPStatusError) or exc.response.status_code not in {429, 503}:
        return None
    try:
        retry_after = float(exc.response.headers.get("Retry-After") or 10.0)
    except (TypeError, ValueError):
        retry_after = 10.0
    return max(1.0, min(retry_after, 60.0))


def build_open_add_episode_id_set(cur, *, product_id: int, product_rows: list[dict]) -> set[int]:
    active_episode_summary_rows = fetch_active_summary_rows(cur=cur, product_id=product_id, summary_type="episode_summary")
    active_episode_scope_keys = {
        str(row.get("scope_key") or "").strip()
        for row in active_episode_summary_rows
        if str(row.get("scope_key") or "").strip()
    }

    open_add_episode_ids: set[int] = set()
    for row in product_rows:
        episode_id = int(row.get("episode_id") or 0)
        if episode_id <= 0:
            continue
        scope_key = f"episode:{episode_id}"
        if scope_key not in active_episode_scope_keys:
            open_add_episode_ids.add(episode_id)
    return open_add_episode_ids


def fetch_product_ready_episode_count(cur, *, product_id: int) -> int:
    cur.execute(
        """
        SELECT ready_episode_count
          FROM tb_story_agent_context_product
         WHERE product_id = %s
        """,
        (product_id,),
    )
    row = cur.fetchone() or {}
    return int(row.get("ready_episode_count") or 0)


def build_sync_repair_episode_id_set(cur, *, product_id: int, product_rows: list[dict]) -> set[int]:
    active_episode_summary_rows = fetch_active_summary_rows(cur=cur, product_id=product_id, summary_type="episode_summary")
    active_episode_scope_keys = {
        str(row.get("scope_key") or "").strip()
        for row in active_episode_summary_rows
        if str(row.get("scope_key") or "").strip()
    }
    ready_episode_count = fetch_product_ready_episode_count(cur, product_id=product_id)

    repair_episode_ids: set[int] = set()
    for row in product_rows:
        episode_id = int(row.get("episode_id") or 0)
        episode_no = int(row.get("episode_no") or 0)
        if episode_id <= 0 or episode_no <= 0:
            continue
        scope_key = f"episode:{episode_id}"
        if scope_key in active_episode_scope_keys and episode_no > ready_episode_count:
            logger.info(
                "story_agent_delta_candidate product_id=%s episode_no=%s reason=sync_repair ready_episode_count=%s has_episode_summary=1",
                product_id,
                episode_no,
                ready_episode_count,
            )
            repair_episode_ids.add(episode_id)
    return repair_episode_ids


def build_signal_repair_episode_id_set(cur, *, product_id: int, product_rows: list[dict]) -> set[int]:
    active_signal_rows = fetch_active_summary_rows(
        cur=cur,
        product_id=product_id,
        summary_type="episode_character_signals",
    )
    active_signal_scope_keys = {
        str(row.get("scope_key") or "").strip()
        for row in active_signal_rows
        if str(row.get("scope_key") or "").strip()
    }

    repair_episode_ids: set[int] = set()
    for row in product_rows:
        episode_id = int(row.get("episode_id") or 0)
        episode_no = int(row.get("episode_no") or 0)
        if episode_id <= 0:
            continue
        scope_key = f"episode:{episode_id}"
        if scope_key not in active_signal_scope_keys:
            logger.info(
                "story_agent_delta_candidate product_id=%s episode_no=%s reason=signal_repair has_episode_character_signals=0",
                product_id,
                episode_no,
            )
            repair_episode_ids.add(episode_id)
    return repair_episode_ids


def build_scene_repair_episode_id_set(cur, *, product_id: int, product_rows: list[dict]) -> set[int]:
    active_scene_rows = fetch_active_summary_rows(
        cur=cur,
        product_id=product_id,
        summary_type="episode_scene_extraction",
    )
    active_episode_summary_rows = fetch_active_summary_rows(
        cur=cur,
        product_id=product_id,
        summary_type="episode_summary",
    )
    episode_summary_id_by_scope = {
        str(row.get("scope_key") or "").strip(): int(row.get("summary_id") or 0)
        for row in active_episode_summary_rows
        if str(row.get("scope_key") or "").strip()
    }
    usable_scene_scope_keys = {
        str(row.get("scope_key") or "").strip()
        for row in active_scene_rows
        if str(row.get("scope_key") or "").strip()
        and int(row.get("summary_id") or 0)
        > int(episode_summary_id_by_scope.get(str(row.get("scope_key") or "").strip()) or 0)
        and _is_usable_episode_scene_payload(
            extract_json_object(str(row.get("summary_text") or "")) or {}
        )
    }

    repair_episode_ids: set[int] = set()
    for row in product_rows:
        episode_id = int(row.get("episode_id") or 0)
        episode_no = int(row.get("episode_no") or 0)
        if episode_id <= 0:
            continue
        scope_key = f"episode:{episode_id}"
        if scope_key in usable_scene_scope_keys:
            continue
        logger.info(
            "story_agent_delta_candidate product_id=%s episode_no=%s reason=scene_repair has_usable_scene=0",
            product_id,
            episode_no,
        )
        repair_episode_ids.add(episode_id)
    return repair_episode_ids


def delta_episode_sort_key(row: dict) -> tuple[int, int]:
    return (int(row.get("episode_no") or 0), int(row.get("episode_id") or 0))


def filter_delta_candidate_rows(cur, rows: Iterable[dict], *, max_delta_episodes: int = 0) -> list[dict]:
    rows_by_product: dict[int, list[dict]] = {}
    for row in rows:
        rows_by_product.setdefault(int(row["product_id"]), []).append(row)

    filtered_rows: list[dict] = []
    for product_id, product_rows in rows_by_product.items():
        open_add_episode_ids = build_open_add_episode_id_set(
            cur,
            product_id=product_id,
            product_rows=product_rows,
        )
        repair_episode_ids = build_sync_repair_episode_id_set(
            cur,
            product_id=product_id,
            product_rows=product_rows,
        )
        signal_repair_episode_ids = build_signal_repair_episode_id_set(
            cur,
            product_id=product_id,
            product_rows=product_rows,
        )
        scene_repair_episode_ids = build_scene_repair_episode_id_set(
            cur,
            product_id=product_id,
            product_rows=product_rows,
        )
        product_filtered_rows: list[dict] = []
        for row in product_rows:
            episode_id = int(row.get("episode_id") or 0)
            if episode_id in open_add_episode_ids:
                next_row = dict(row)
                next_row["_delta_reason"] = "open_add"
                product_filtered_rows.append(next_row)
            elif episode_id in repair_episode_ids:
                next_row = dict(row)
                next_row["_delta_reason"] = "sync_repair"
                product_filtered_rows.append(next_row)
            elif episode_id in signal_repair_episode_ids:
                next_row = dict(row)
                next_row["_delta_reason"] = "signal_repair"
                product_filtered_rows.append(next_row)
            elif episode_id in scene_repair_episode_ids:
                next_row = dict(row)
                next_row["_delta_reason"] = "scene_repair"
                product_filtered_rows.append(next_row)
        reason_priority = {
            "open_add": 0,
            "sync_repair": 1,
            "signal_repair": 2,
            "scene_repair": 3,
        }
        product_filtered_rows.sort(
            key=lambda row: (
                reason_priority.get(str(row.get("_delta_reason") or ""), 99),
                *delta_episode_sort_key(row),
            )
        )
        if max_delta_episodes > 0:
            product_filtered_rows = product_filtered_rows[:max_delta_episodes]
        filtered_rows.extend(product_filtered_rows)
    return filtered_rows


def build_delta_scope_plans(cur, rows: Iterable[dict]) -> list[DeltaBuildScopePlan]:
    rows_by_product: dict[int, list[dict]] = {}
    for row in rows:
        rows_by_product.setdefault(int(row["product_id"]), []).append(row)

    plans: list[DeltaBuildScopePlan] = []
    for product_id, product_rows in sorted(rows_by_product.items()):
        touched_episode_ids = tuple(
            sorted(
                set(
                    int(row.get("episode_id") or 0)
                    for row in product_rows
                    if int(row.get("episode_id") or 0) > 0
                )
            )
        )
        touched_episode_nos = tuple(
            sorted(
                set(
                    int(row.get("episode_no") or 0)
                    for row in product_rows
                    if int(row.get("episode_no") or 0) > 0
                )
            )
        )
        if not touched_episode_nos:
            continue
        episode_delta_reasons = tuple(
            sorted(
                (
                    int(row.get("episode_id") or 0),
                    int(row.get("episode_no") or 0),
                    str(row.get("_delta_reason") or "open_add"),
                )
                for row in product_rows
                if int(row.get("episode_id") or 0) > 0 and int(row.get("episode_no") or 0) > 0
            )
        )
        plans.append(
            DeltaBuildScopePlan(
                product_id=product_id,
                product_title=str(product_rows[0].get("title") or "").strip(),
                touched_episode_ids=touched_episode_ids,
                touched_episode_nos=touched_episode_nos,
                episode_delta_reasons=episode_delta_reasons,
                touched_range_scopes=tuple(select_touched_range_scopes(list(touched_episode_nos))),
                rebuild_product_summary=True,
                rebuild_character_inventory=True,
                rebuild_relation_inventory=True,
            )
        )
    return plans


def print_delta_scope_plans(plans: list[DeltaBuildScopePlan]) -> None:
    print(f"mode=delta plans={len(plans)}")
    for plan in plans:
        range_labels = ", ".join(scope_key for scope_key, _, _ in plan.touched_range_scopes) or "-"
        episode_labels = ", ".join(str(value) for value in plan.touched_episode_nos) or "-"
        episode_reason_labels = ", ".join(
            f"{episode_no}:{reason}"
            for _, episode_no, reason in plan.episode_delta_reasons
        ) or "-"
        print(
            "delta",
            f"product_id={plan.product_id}",
            f"title={plan.product_title or '-'}",
            f"episodes={episode_labels}",
            f"episode_reasons={episode_reason_labels}",
            f"ranges={range_labels}",
            f"rebuild_product_summary={int(plan.rebuild_product_summary)}",
            f"rebuild_character_inventory={int(plan.rebuild_character_inventory)}",
            f"rebuild_relation_inventory={int(plan.rebuild_relation_inventory)}",
        )


def build_range_summary_text(start_episode: int, end_episode: int, rows: list[dict]) -> str:
    sampled_rows = pick_spread_rows(rows, limit=4)
    merged_keywords: list[str] = []
    keyword_seen: set[str] = set()
    lines = [f"[{start_episode}~{end_episode}화] 구간 요약"]
    for row in sampled_rows:
        parsed = parse_summary_text(str(row.get("summary_text") or ""))
        first_bullet = next((bullet for bullet in list(parsed["bullets"]) if bullet), "")
        episode_no = int(row.get("episode_from") or 0)
        if first_bullet:
            lines.append(f"- {episode_no}화: {first_bullet}")
        for keyword in list(parsed["keywords"]):
            if keyword in keyword_seen:
                continue
            keyword_seen.add(keyword)
            merged_keywords.append(keyword)
            if len(merged_keywords) >= 10:
                break
        if len(merged_keywords) >= 10:
            continue
    lines.append(f"- 키워드: {', '.join(merged_keywords)}" if merged_keywords else "- 키워드:")
    return "\n".join(lines).strip()


def build_product_summary_text(product_title: str, rows: list[dict]) -> str:
    sampled_rows = pick_spread_rows(rows, limit=4)
    merged_keywords: list[str] = []
    keyword_seen: set[str] = set()
    lines = [f"[작품 전체] {product_title or '요약'}"]
    for row in sampled_rows:
        parsed = parse_summary_text(str(row.get("summary_text") or ""))
        first_bullet = next((bullet for bullet in list(parsed["bullets"]) if bullet), "")
        from_episode = int(row.get("episode_from") or 0)
        to_episode = int(row.get("episode_to") or 0)
        if first_bullet:
            if from_episode and to_episode and from_episode != to_episode:
                lines.append(f"- {from_episode}~{to_episode}화: {first_bullet}")
            elif from_episode:
                lines.append(f"- {from_episode}화: {first_bullet}")
            else:
                lines.append(f"- {first_bullet}")
        for keyword in list(parsed["keywords"]):
            if keyword in keyword_seen:
                continue
            keyword_seen.add(keyword)
            merged_keywords.append(keyword)
            if len(merged_keywords) >= 12:
                break
        if len(merged_keywords) >= 12:
            continue
    lines.append(f"- 키워드: {', '.join(merged_keywords)}" if merged_keywords else "- 키워드:")
    return "\n".join(lines).strip()


def validate_compound_summary_text(summary_type: str, summary_text: str) -> tuple[bool, str]:
    text = str(summary_text or "").strip()
    if not text:
        return False, "empty_summary_text"

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return False, "empty_summary_lines"

    content_bullets = [
        line
        for line in lines[1:]
        if line.startswith("- ") and not line.startswith("- 키워드:")
    ]
    if not content_bullets:
        return False, f"{summary_type}_missing_content_bullets"

    return True, "ok"


def build_character_scope_key(name: str) -> str:
    slug = re.sub(r"[^가-힣A-Za-z0-9]", "", (name or "").strip().lower())
    return f"character:{slug}" if slug else "character:unknown"


def is_valid_character_token(token: str) -> bool:
    normalized = (token or "").strip()
    if not re.fullmatch(r"[가-힣]{3,4}", normalized):
        return False
    if normalized in CHARACTER_STOPWORDS:
        return False
    if normalized[0] not in COMMON_KOREAN_SURNAMES:
        return False
    return True


def extract_character_candidates(rows: list[dict]) -> list[dict[str, object]]:
    candidate_map: dict[str, dict[str, object]] = {}
    for row in rows:
        episode_no = int(row.get("episode_from") or 0)
        parsed = parse_summary_text(str(row.get("summary_text") or ""))
        bullet_text = " ".join(list(parsed["bullets"]))
        tokens: set[str] = set()
        for token in NAME_WITH_PARTICLE_RE.findall(bullet_text):
            if is_valid_character_token(token):
                tokens.add(token)
        for token in tokens:
            current = candidate_map.setdefault(
                token,
                {
                    "name": token,
                    "episode_nos": set(),
                    "summary_rows": [],
                    "keywords": set(),
                },
            )
            current["episode_nos"].add(episode_no)
            current["summary_rows"].append(row)
            current["keywords"].update(list(parsed["keywords"]))
    ranked = sorted(
        candidate_map.values(),
        key=lambda item: (-len(item["episode_nos"]), str(item["name"])),
    )
    return [item for item in ranked if len(item["episode_nos"]) >= 2][:8]


def deactivate_missing_active_scopes(cur, product_id: int, summary_type: str, valid_scope_keys: set[str]) -> None:
    if valid_scope_keys:
        placeholders = ", ".join(["%s"] * len(valid_scope_keys))
        cur.execute(
            f"""
            UPDATE tb_story_agent_context_summary
               SET is_active = 'N'
             WHERE product_id = %s
               AND summary_type = %s
               AND is_active = 'Y'
               AND scope_key NOT IN ({placeholders})
            """,
            (product_id, summary_type, *sorted(valid_scope_keys)),
        )
        return
    cur.execute(
        """
        UPDATE tb_story_agent_context_summary
           SET is_active = 'N'
         WHERE product_id = %s
           AND summary_type = %s
           AND is_active = 'Y'
        """,
        (product_id, summary_type),
    )


def deactivate_active_scope(cur, *, product_id: int, summary_type: str, scope_key: str) -> int:
    normalized_scope_key = str(scope_key or "").strip()
    if not normalized_scope_key:
        return 0
    cur.execute(
        """
        UPDATE tb_story_agent_context_summary
           SET is_active = 'N'
         WHERE product_id = %s
           AND summary_type = %s
           AND scope_key = %s
           AND is_active = 'Y'
        """,
        (product_id, summary_type, normalized_scope_key),
    )
    return int(cur.rowcount or 0)


def build_character_snapshot_text(name: str, candidate: dict[str, object]) -> str:
    episode_nos = sorted(int(item) for item in set(candidate["episode_nos"]))
    sampled_rows = pick_spread_rows(list(candidate["summary_rows"]), limit=3)
    merged_keywords: list[str] = []
    keyword_seen: set[str] = set()
    lines = [f"[인물] {name}"]
    lines.append(f"- 등장 회차: {', '.join(str(no) for no in episode_nos[:8])}")
    for row in sampled_rows:
        parsed = parse_summary_text(str(row.get("summary_text") or ""))
        first_bullet = next((bullet for bullet in list(parsed["bullets"]) if bullet), "")
        episode_no = int(row.get("episode_from") or 0)
        if first_bullet:
            lines.append(f"- {episode_no}화: {first_bullet}")
        for keyword in list(parsed["keywords"]):
            if keyword == name or keyword in keyword_seen:
                continue
            keyword_seen.add(keyword)
            merged_keywords.append(keyword)
            if len(merged_keywords) >= 8:
                break
        if len(merged_keywords) >= 8:
            continue
    lines.append(f"- 관련 키워드: {', '.join(merged_keywords)}" if merged_keywords else "- 관련 키워드:")
    return "\n".join(lines).strip()


def build_named_character_scope_key(name: str) -> str:
    slug = re.sub(r"[^가-힣A-Za-z0-9]", "", (name or "").strip().lower())
    return f"named:{slug}" if slug else ""


def build_protagonist_scope_key(name: str | None = None, *, first_person: bool = False) -> str:
    if first_person:
        return "protagonist:first_person"
    slug = re.sub(r"[^가-힣A-Za-z0-9]", "", (name or "").strip().lower())
    return f"protagonist:named:{slug}" if slug else "protagonist:first_person"


def looks_like_first_person_narrative(episode_texts_by_no: dict[int, str]) -> bool:
    sample_text = "\n".join(
        str(episode_texts_by_no[episode_no])
        for episode_no in sorted(episode_texts_by_no.keys())[:3]
        if str(episode_texts_by_no.get(episode_no) or "").strip()
    )
    if not sample_text:
        return False
    first_person_hits = len(re.findall(r"\b(나는|내가|난|내\s|나를|나에게|내겐|내겐)\b", sample_text))
    quote_hits = sample_text.count('"') + sample_text.count("“") + sample_text.count("”")
    return first_person_hits >= 6 and first_person_hits >= max(2, quote_hits // 8)


def build_rp_character_targets(
    episode_rows: list[dict],
    episode_texts_by_no: dict[int, str],
) -> list[dict[str, object]]:
    targets: list[dict[str, object]] = []
    named_candidates = extract_character_candidates(episode_rows)
    used_names: set[str] = set()
    if looks_like_first_person_narrative(episode_texts_by_no):
        targets.append(
            {
                "character_key": build_protagonist_scope_key(first_person=True),
                "display_name": "주인공",
                "reference_name": "주인공",
                "is_protagonist": True,
                "is_first_person": True,
                "aliases": ["주인공"],
            }
        )
    elif named_candidates:
        protagonist_name = str(named_candidates[0]["name"]).strip()
        used_names.add(protagonist_name)
        targets.append(
            {
                "character_key": build_protagonist_scope_key(protagonist_name),
                "display_name": protagonist_name,
                "reference_name": protagonist_name,
                "is_protagonist": True,
                "is_first_person": False,
                "aliases": [protagonist_name, "주인공"],
            }
        )
    else:
        targets.append(
            {
                "character_key": build_protagonist_scope_key(first_person=True),
                "display_name": "주인공",
                "reference_name": "주인공",
                "is_protagonist": True,
                "is_first_person": True,
                "aliases": ["주인공"],
            }
        )

    for candidate in named_candidates:
        name = str(candidate["name"]).strip()
        if not name or name in used_names:
            continue
        scope_key = build_named_character_scope_key(name)
        if not scope_key:
            continue
        targets.append(
            {
                "character_key": scope_key,
                "display_name": name,
                "reference_name": name,
                "is_protagonist": False,
                "is_first_person": False,
                "aliases": [name],
            }
        )
        used_names.add(name)
        if len(targets) >= 5:
            break
    return targets[:5]


def build_rp_character_plan_user_prompt(episode_rows: list[dict[str, object]], episode_texts_by_no: dict[int, str]) -> str:
    lines: list[str] = []
    is_first_person = looks_like_first_person_narrative(episode_texts_by_no)
    lines.append(f"is_first_person_candidate: {'Y' if is_first_person else 'N'}")
    lines.append("아래는 공개 회차 episode_summary 발췌다.")
    for row in episode_rows[:60]:
        episode_no = int(row.get("episode_from") or 0)
        parsed = parse_summary_text(str(row.get("summary_text") or ""))
        bullets = [bullet for bullet in list(parsed["bullets"]) if bullet][:3]
        keywords = [keyword for keyword in list(parsed["keywords"]) if keyword][:8]
        lines.append(f"[{episode_no}화]")
        for bullet in bullets:
            lines.append(f"- 사건: {bullet}")
        if keywords:
            lines.append(f"- 핵심: {', '.join(keywords)}")
    return "\n".join(lines)


def normalize_rp_character_plan(
    payload: dict | None,
    episode_rows: list[dict[str, object]],
    episode_texts_by_no: dict[int, str],
) -> list[dict[str, object]]:
    available_episode_nos = {
        int(row.get("episode_from") or 0)
        for row in episode_rows
        if int(row.get("episode_from") or 0) > 0
    }
    if not payload:
        return []
    characters = payload.get("characters") or []
    if not isinstance(characters, list):
        return []

    normalized_targets: list[dict[str, object]] = []
    seen_keys: set[str] = set()
    first_person_candidate = looks_like_first_person_narrative(episode_texts_by_no)

    for item in characters:
        if not isinstance(item, dict):
            continue
        display_name = str(item.get("display_name") or "").strip()
        aliases = [str(alias).strip() for alias in (item.get("aliases") or []) if str(alias).strip()]
        is_protagonist = parse_yes_no_flag(item.get("is_protagonist"))
        is_first_person = parse_yes_no_flag(item.get("is_first_person")) if is_protagonist else False
        if not display_name and is_protagonist:
            display_name = "주인공"
        if not display_name:
            continue
        if display_name in CHARACTER_STOPWORDS and not is_protagonist:
            continue

        character_key = (
            build_protagonist_scope_key(display_name if not is_first_person else None, first_person=is_first_person)
            if is_protagonist
            else build_named_character_scope_key(display_name)
        )
        if not character_key or character_key in seen_keys:
            continue
        seen_keys.add(character_key)

        merged_aliases = [display_name, *aliases]
        if is_protagonist and "주인공" not in merged_aliases:
            merged_aliases.append("주인공")
        unique_aliases: list[str] = []
        for alias in merged_aliases:
            if alias and alias not in unique_aliases:
                unique_aliases.append(alias)

        evidence_episodes = [
            int(no)
            for no in (item.get("evidence_episodes") or [])
            if isinstance(no, int) and no in available_episode_nos
        ][:6]

        collection_rules = item.get("collection_rules") or {}
        speaker_anchors = [
            str(anchor).strip()
            for anchor in (collection_rules.get("speaker_anchors") or unique_aliases)
            if str(anchor).strip()
        ]
        exclude_tokens = [
            str(token).strip()
            for token in (collection_rules.get("exclude_tokens") or [])
            if str(token).strip()
        ]
        priority_patterns = [
            str(pattern).strip()
            for pattern in (collection_rules.get("priority_patterns") or [])
            if str(pattern).strip()
        ][:4]
        interaction_axes = [
            str(axis).strip()
            for axis in (item.get("interaction_axes") or [])
            if str(axis).strip()
        ][:5]

        normalized_targets.append(
            {
                "character_key": character_key,
                "display_name": display_name,
                "reference_name": display_name,
                "is_protagonist": is_protagonist,
                "is_first_person": is_first_person if is_protagonist else False,
                "aliases": unique_aliases[:6],
                "personality_hypothesis": [
                    str(value).strip()
                    for value in (item.get("personality_hypothesis") or [])
                    if str(value).strip()
                ][:2],
                "interaction_axes": interaction_axes,
                "baseline_attitude_hypothesis": str(item.get("baseline_attitude_hypothesis") or "").strip() or "무난",
                "evidence_episodes": evidence_episodes,
                "collection_rules": {
                    "use_dialogue": bool(collection_rules.get("use_dialogue", True)),
                    "use_monologue": bool(collection_rules.get("use_monologue", is_protagonist and first_person_candidate)),
                    "speaker_anchors": speaker_anchors[:6],
                    "exclude_tokens": exclude_tokens[:10],
                    "priority_patterns": priority_patterns,
                },
            }
        )
        if len(normalized_targets) >= 5:
            break

    return normalized_targets[:5]


def normalize_rp_guard_token(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip().lower()


def _target_allows_role_like_persona_display(target: dict[str, object]) -> bool:
    display_name = str(target.get("display_name") or target.get("reference_name") or "").strip()
    if normalize_signal_entity_label(display_name) in NON_PERSONA_GENERIC_LABELS:
        return False
    display_safety = dict(target.get("display_safety") or {})
    return (
        str(display_safety.get("status") or "").strip() == "pass"
        and str(display_safety.get("reason") or "").strip() == "stable_persona_identity"
    )


def get_rp_target_skip_reason(target: dict[str, object]) -> str:
    display_name = str(target.get("display_name") or target.get("reference_name") or "").strip()
    display_safety = dict(target.get("display_safety") or {})
    display_safety_status = str(display_safety.get("status") or "").strip()
    if is_generic_character_label(display_name) and not _target_allows_role_like_persona_display(target):
        return "generic_display_name"
    if display_safety_status and display_safety_status != "pass":
        return f"display_safety_{display_safety_status}"
    return ""


def has_enough_rp_example_texts(example_texts: list[str]) -> bool:
    return len([text for text in example_texts if str(text or "").strip()]) >= RP_PROFILE_MIN_EXAMPLE_TEXTS


def _append_unique_text(values: list[str], value: str, *, limit: int = 8) -> None:
    text = str(value or "").strip()
    if text and text not in values and len(values) < limit:
        values.append(text)


def extract_json_object(raw_text: str) -> dict | None:
    raw = str(raw_text or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def parse_yes_no_flag(value: str, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 1
    normalized = str(value or "").strip().lower()
    if not normalized:
        return default
    return normalized in {"y", "yes", "true", "1", "t"}


def normalize_signal_name_list(values: object, *, limit: int = 4) -> list[str]:
    names: list[str] = []
    for value in list(values or []):
        name = str(value).strip()
        normalized = normalize_signal_entity_label(name)
        if not name or not normalized or normalized in GENERIC_CHARACTER_LABELS:
            continue
        if _identity_claim_label_is_blocked(name):
            continue
        if name not in names:
            names.append(name[:40])
        if len(names) >= limit:
            break
    return names


def append_unique_name_signal(names: list[str], value: object, *, limit: int = 4) -> list[str]:
    name = str(value or "").strip()
    if not name:
        return names
    if normalize_signal_name_list([name], limit=1) and name[:40] not in names:
        names.append(name[:40])
    return names[:limit]


def parse_episode_character_signals_structured_text(raw_text: str) -> dict | None:
    raw = str(raw_text or "").strip()
    if not raw:
        return None

    payload: dict[str, object] = {
        "mentioned_characters": [],
        "cliffhanger_hooks": [],
    }
    characters_by_name: dict[str, dict[str, object]] = {}
    pending_relations: list[tuple[str, dict[str, str]]] = []

    for raw_line in raw.splitlines():
        line = str(raw_line or "").strip()
        if not line:
            continue
        if line.startswith("```"):
            continue

        upper_line = line.upper()
        if upper_line.startswith("EPISODE:"):
            episode_text = line.split(":", 1)[1].strip()
            try:
                payload["episode_no"] = int(re.sub(r"[^\d]", "", episode_text))
            except Exception:
                pass
            continue

        if upper_line.startswith("HOOK:"):
            hook = line.split(":", 1)[1].strip()
            if hook:
                hooks = list(payload.get("cliffhanger_hooks") or [])
                hooks.append(hook[:120])
                payload["cliffhanger_hooks"] = hooks[:3]
            continue

        if upper_line.startswith("CHAR:"):
            body = line.split(":", 1)[1].strip()
            if not body:
                continue
            parts = [part.strip() for part in body.split("|")]
            display_name = str(parts[0] or "").strip()
            if not display_name:
                continue
            character_item: dict[str, object] = {
                "display_name": display_name,
                "aliases": [],
                "is_protagonist": False,
                "is_work_protagonist": False,
                "is_episode_focal": False,
                "is_first_person": False,
                "narration_names": [],
                "social_call_names": [],
                "persona_names": [],
                "real_names": [],
                "entity_kind": "person",
                "scene_weight": "low",
                "role_in_episode": "support",
                "voice_mode": "narration_only",
                "action_tags": [],
                "affect_tags": [],
                "relation_edges": [],
                "identity_claims": [],
            }
            for part in parts[1:]:
                if "=" not in part:
                    continue
                key, value = [segment.strip() for segment in part.split("=", 1)]
                normalized_key = key.lower()
                if normalized_key == "aliases":
                    aliases = [alias.strip() for alias in value.split(",") if alias.strip()]
                    character_item["aliases"] = aliases[:6]
                elif normalized_key == "protagonist":
                    is_work_protagonist = parse_yes_no_flag(value)
                    character_item["is_protagonist"] = is_work_protagonist
                    character_item["is_work_protagonist"] = is_work_protagonist
                    character_item["is_episode_focal"] = is_work_protagonist
                elif normalized_key == "work_protagonist":
                    is_work_protagonist = parse_yes_no_flag(value)
                    character_item["is_protagonist"] = is_work_protagonist
                    character_item["is_work_protagonist"] = is_work_protagonist
                elif normalized_key == "episode_focal":
                    character_item["is_episode_focal"] = parse_yes_no_flag(value)
                elif normalized_key == "first_person":
                    character_item["is_first_person"] = parse_yes_no_flag(value)
                elif normalized_key == "narration_names":
                    character_item["narration_names"] = normalize_signal_name_list(value.split(","), limit=4)
                elif normalized_key == "social_call_names":
                    character_item["social_call_names"] = normalize_signal_name_list(value.split(","), limit=4)
                elif normalized_key == "persona_names":
                    character_item["persona_names"] = normalize_signal_name_list(value.split(","), limit=4)
                elif normalized_key == "real_names":
                    character_item["real_names"] = normalize_signal_name_list(value.split(","), limit=4)
                elif normalized_key == "kind":
                    character_item["entity_kind"] = value or "person"
                elif normalized_key == "weight":
                    character_item["scene_weight"] = value or "low"
                elif normalized_key == "role":
                    character_item["role_in_episode"] = value or "support"
                elif normalized_key == "voice":
                    character_item["voice_mode"] = value or "narration_only"
                elif normalized_key == "action":
                    action_tags = [tag.strip() for tag in value.split(",") if tag.strip()]
                    character_item["action_tags"] = action_tags[:4]
                elif normalized_key == "affect":
                    affect_tags = [tag.strip() for tag in value.split(",") if tag.strip()]
                    character_item["affect_tags"] = affect_tags[:4]
            characters = list(payload.get("mentioned_characters") or [])
            characters.append(character_item)
            payload["mentioned_characters"] = characters[:6]
            characters_by_name[normalize_signal_entity_label(display_name)] = character_item
            for alias in list(character_item.get("aliases") or [])[:6]:
                normalized_alias = normalize_signal_entity_label(str(alias))
                if normalized_alias and normalized_alias not in characters_by_name:
                    characters_by_name[normalized_alias] = character_item
            continue

        if upper_line.startswith("REL:"):
            body = line.split(":", 1)[1].strip()
            if not body:
                continue
            parts = [part.strip() for part in body.split("|")]
            if len(parts) < 3:
                continue
            source_label = parts[0]
            target_label = parts[1]
            relation_tag = parts[2]
            direction = parts[3].strip().lower() if len(parts) >= 4 else "to_target"
            if not source_label or not target_label or not relation_tag:
                continue
            pending_relations.append(
                (
                    normalize_signal_entity_label(source_label),
                    {
                        "target_label": target_label[:40],
                        "relation_tag": relation_tag[:20],
                        "direction": direction,
                    },
                )
            )

    for normalized_source, relation_edge in pending_relations:
        source_character = characters_by_name.get(normalized_source)
        if not source_character:
            continue
        relation_edges = list(source_character.get("relation_edges") or [])
        relation_edges.append(relation_edge)
        source_character["relation_edges"] = relation_edges[:5]

    mentioned_characters = list(payload.get("mentioned_characters") or [])
    cliffhanger_hooks = list(payload.get("cliffhanger_hooks") or [])
    if not mentioned_characters and not cliffhanger_hooks:
        return None
    return payload


def build_episode_character_signals_user_prompt(
    row: dict[str, object],
    summary_text: str,
) -> str:
    episode_no = int(row.get("episode_no") or row.get("episode_from") or 0)
    title = str(row.get("title") or "").strip()
    episode_title = str(row.get("episode_title") or "").strip()
    return (
        f"작품명: {title}\n"
        f"episode_no: {episode_no}\n"
        f"회차 제목: {episode_title}\n"
        "아래는 해당 회차의 episode_summary다.\n"
        "이 요약에서 드러나는 캐릭터/관계/행동 신호만 지정된 JSON schema로 추출하라.\n"
        "코드블록, 설명문은 쓰지 마라.\n\n"
        f"{summary_text}"
    )


def normalize_signal_entity_label(value: str) -> str:
    normalized = re.sub(r"\s+", "", str(value or "").strip())
    if not normalized:
        return ""
    stripped = re.sub(r"[!?.…~]+$", "", normalized)
    return stripped


def normalize_episode_character_signals_payload(
    payload: dict | None,
    *,
    episode_no: int,
) -> dict[str, object]:
    normalized_characters: list[dict[str, object]] = []
    raw_relation_edges_by_key: dict[str, list[dict[str, str]]] = {}
    raw_identity_claims_by_key: dict[str, list[dict[str, str]]] = {}
    alias_to_character_key: dict[str, str] = {}
    seen_keys: set[str] = set()
    for item in list((payload or {}).get("mentioned_characters") or []):
        if not isinstance(item, dict):
            continue
        display_name = str(item.get("display_name") or "").strip()
        if not display_name:
            continue
        legacy_is_protagonist = parse_yes_no_flag(item.get("is_protagonist"))
        is_work_protagonist = parse_yes_no_flag(item.get("is_work_protagonist"), default=legacy_is_protagonist)
        is_episode_focal = parse_yes_no_flag(item.get("is_episode_focal"), default=legacy_is_protagonist)
        is_protagonist = is_work_protagonist
        is_first_person = parse_yes_no_flag(item.get("is_first_person")) if is_work_protagonist else False
        entity_kind = str(item.get("entity_kind") or "person").strip().lower() or "person"
        if entity_kind not in {"person", "stable_role", "collective", "other"}:
            entity_kind = "person"

        character_key = (
            build_protagonist_scope_key(display_name if not is_first_person else None, first_person=is_first_person)
            if is_protagonist
            else build_named_character_scope_key(display_name)
        )
        if not character_key or character_key in seen_keys:
            continue
        seen_keys.add(character_key)

        aliases = []
        for alias in [display_name, *list(item.get("aliases") or [])]:
            alias_text = str(alias).strip()
            if alias_text and alias_text not in aliases:
                aliases.append(alias_text)
        narration_names = normalize_signal_name_list(item.get("narration_names"), limit=4)
        social_call_names = normalize_signal_name_list(item.get("social_call_names"), limit=4)
        persona_names = normalize_signal_name_list(item.get("persona_names"), limit=4)
        real_names = normalize_signal_name_list(item.get("real_names"), limit=4)

        scene_weight = str(item.get("scene_weight") or "low").strip().lower()
        if scene_weight not in {"high", "medium", "low"}:
            scene_weight = "low"
        role_in_episode = str(item.get("role_in_episode") or "support").strip().lower()
        if role_in_episode not in {"lead", "counterpart", "support", "obstacle"}:
            role_in_episode = "support"
        voice_mode = str(item.get("voice_mode") or "narration_only").strip().lower()
        if voice_mode not in {"dialogue", "monologue", "narration_only"}:
            voice_mode = "narration_only"

        relation_edges: list[dict[str, str]] = []
        for edge in list(item.get("relation_edges") or []):
            if not isinstance(edge, dict):
                continue
            target_label = str(edge.get("target_label") or "").strip()
            relation_tag = str(edge.get("relation_tag") or "").strip()
            direction = str(edge.get("direction") or "").strip().lower()
            if not target_label or not relation_tag:
                continue
            if direction not in {"to_target", "from_target", "mutual"}:
                direction = "to_target"
            relation_edges.append(
                {
                    "target_label": target_label[:40],
                    "relation_tag": relation_tag[:20],
                    "direction": direction,
                }
            )
            if len(relation_edges) >= 5:
                break

        identity_claims: list[dict[str, str]] = []
        for claim in list(item.get("identity_claims") or []):
            if not isinstance(claim, dict):
                continue
            target_label = str(claim.get("target_label") or "").strip()
            claim_type = str(claim.get("claim_type") or "").strip().lower()
            evidence = str(claim.get("evidence") or "").strip()
            if not target_label or claim_type not in IDENTITY_CLAIM_TYPES:
                continue
            identity_claims.append(
                {
                    "target_label": target_label[:40],
                    "claim_type": claim_type,
                    "evidence": evidence[:80],
                }
            )
            if len(identity_claims) >= 4:
                break

        normalized_characters.append(
            {
                "character_key": character_key,
                "display_name": display_name,
                "aliases": aliases[:6],
                "is_protagonist": is_protagonist,
                "is_work_protagonist": is_work_protagonist,
                "is_episode_focal": is_episode_focal,
                "is_first_person": is_first_person,
                "narration_names": narration_names,
                "social_call_names": social_call_names,
                "persona_names": persona_names,
                "real_names": real_names,
                "entity_kind": entity_kind,
                "scene_weight": scene_weight,
                "role_in_episode": role_in_episode,
                "voice_mode": voice_mode,
                "action_tags": [
                    str(tag).strip()[:20]
                    for tag in list(item.get("action_tags") or [])
                    if str(tag).strip()
                ][:4],
                "affect_tags": [
                    str(tag).strip()[:20]
                    for tag in list(item.get("affect_tags") or [])
                    if str(tag).strip()
                ][:4],
                "relation_edges": [],
                "identity_claims": [],
                "episode_no": episode_no,
            }
        )
        raw_relation_edges_by_key[character_key] = relation_edges
        raw_identity_claims_by_key[character_key] = identity_claims
        for alias in aliases[:6]:
            normalized_alias = normalize_signal_entity_label(alias)
            if normalized_alias:
                alias_to_character_key.setdefault(normalized_alias, character_key)
        normalized_display_name = normalize_signal_entity_label(display_name)
        if normalized_display_name:
            alias_to_character_key.setdefault(normalized_display_name, character_key)

    for character in normalized_characters:
        character_key = str(character.get("character_key") or "").strip()
        normalized_relation_edges: list[dict[str, str | None]] = []
        for edge in raw_relation_edges_by_key.get(character_key, []):
            target_label = str(edge.get("target_label") or "").strip()
            if not target_label:
                continue
            normalized_target_label = normalize_signal_entity_label(target_label)
            normalized_relation_edges.append(
                {
                    "target_label": target_label[:40],
                    "target_key": str(alias_to_character_key.get(normalized_target_label) or "").strip() or None,
                    "relation_tag": str(edge.get("relation_tag") or "").strip()[:20],
                    "direction": str(edge.get("direction") or "").strip().lower() or "to_target",
                }
            )
            if len(normalized_relation_edges) >= 5:
                break
        character["relation_edges"] = normalized_relation_edges

        normalized_identity_claims: list[dict[str, str | None]] = []
        for claim in raw_identity_claims_by_key.get(character_key, []):
            target_label = str(claim.get("target_label") or "").strip()
            if not target_label:
                continue
            normalized_target_label = normalize_signal_entity_label(target_label)
            if not normalized_target_label or normalized_target_label in GENERIC_CHARACTER_LABELS:
                continue
            normalized_identity_claims.append(
                {
                    "target_label": target_label[:40],
                    "target_key": str(alias_to_character_key.get(normalized_target_label) or "").strip() or None,
                    "normalized_target_label": normalized_target_label,
                    "claim_type": str(claim.get("claim_type") or "").strip().lower(),
                    "evidence": str(claim.get("evidence") or "").strip()[:80],
                }
            )
            if len(normalized_identity_claims) >= 4:
                break
        character["identity_claims"] = normalized_identity_claims
        persona_names = list(character.get("persona_names") or [])
        real_names = list(character.get("real_names") or [])
        for claim in normalized_identity_claims:
            claim_type = str(claim.get("claim_type") or "")
            if claim_type in SOCIAL_PERSONA_IDENTITY_CLAIM_TYPES:
                persona_names = append_unique_name_signal(persona_names, claim.get("target_label"), limit=4)
            elif claim_type in REAL_NAME_IDENTITY_CLAIM_TYPES:
                real_names = append_unique_name_signal(real_names, claim.get("target_label"), limit=4)
        character["persona_names"] = persona_names
        character["real_names"] = real_names

    cliffhanger_hooks = [
        str(value).strip()[:120]
        for value in list((payload or {}).get("cliffhanger_hooks") or [])
        if str(value).strip()
    ][:3]

    return {
        "episode_no": episode_no,
        "mentioned_characters": normalized_characters[:6],
        "cliffhanger_hooks": cliffhanger_hooks,
    }


def build_rp_dialogue_collection_user_prompt(target: dict[str, object], normalized_text: str) -> str:
    if bool(target.get("is_protagonist")) and bool(target.get("is_first_person")):
        role_line = "1인칭 서술 작품의 주인공이다."
    else:
        role_line = f"대상 캐릭터명: {str(target.get('reference_name') or '').strip()}"
    aliases = [
        str(alias).strip()
        for alias in [target.get("display_name"), *list(target.get("aliases") or [])]
        if str(alias).strip()
    ]
    return (
        f"{role_line}\n"
        f"별칭 후보: {', '.join(aliases[:10])}\n"
        "아래 원문에서 대상 캐릭터가 실제로 말한 항목만 JSON으로 뽑아라.\n"
        "원문이 <episode no=\"N\"> 형식이면 episode_no는 해당 N을 사용하라.\n\n"
        f"원문:\n{normalized_text[:EPISODE_SUMMARY_MAX_INPUT_CHARS]}"
    )


def build_rp_profile_synthesis_user_prompt(
    target: dict[str, object],
    dialogue_items: list[dict[str, object]],
    summary_context_lines: list[str],
    inventory_item: dict[str, object] | None = None,
    relation_context_lines: list[str] | None = None,
) -> str:
    source_lines = []
    for item in dialogue_items:
        example_score = int(item.get("example_score") or 0)
        source_type = (
            f"example_candidate:{example_score}"
            if bool(item.get("is_example_candidate"))
            else f"source:{example_score}"
        )
        kind = str(item.get("kind") or "dialogue").strip()
        context = str(item.get("context") or "").strip()[:20]
        text_value = str(item.get("text") or "").strip()
        if not text_value:
            continue
        source_lines.append(f"- {source_type} | {kind} | {context} | {text_value}")
    inventory_lines: list[str] = []
    if inventory_item:
        first_seen_episode_no = int(inventory_item.get("first_seen_episode_no") or 0)
        distinct_episode_count = int(inventory_item.get("distinct_episode_count") or 0)
        summary_mention_count = int(inventory_item.get("summary_mention_count") or 0)
        voice_evidence_count = int(inventory_item.get("voice_evidence_count") or 0)
        if first_seen_episode_no > 0:
            inventory_lines.append(f"- 최초 등장: {first_seen_episode_no}화")
        if distinct_episode_count > 0:
            inventory_lines.append(f"- 반복 등장도: {distinct_episode_count}화")
        if summary_mention_count > 0:
            inventory_lines.append(f"- summary 언급 수: {summary_mention_count}")
        if voice_evidence_count > 0:
            inventory_lines.append(f"- 보이스 근거 수: {voice_evidence_count}")
        for field_label, field_name in [
            ("장면 중심성", "scene_centrality"),
            ("별칭 안정성", "alias_stability"),
            ("행동 존재감", "action_presence"),
            ("관계 존재감", "relation_presence"),
        ]:
            field_value = str(inventory_item.get(field_name) or "").strip()
            if field_value:
                inventory_lines.append(f"- {field_label}: {field_value}")
        dominant_action_tags = [str(value).strip() for value in (inventory_item.get("dominant_action_tags") or []) if str(value).strip()]
        dominant_affect_tags = [str(value).strip() for value in (inventory_item.get("dominant_affect_tags") or []) if str(value).strip()]
        if dominant_action_tags:
            inventory_lines.append(f"- 주요 행동 태그: {', '.join(dominant_action_tags[:5])}")
        if dominant_affect_tags:
            inventory_lines.append(f"- 주요 정서 태그: {', '.join(dominant_affect_tags[:5])}")
    return (
        f"캐릭터명: {str(target.get('display_name') or '').strip()}\n"
        f"aliases: {', '.join(str(alias).strip() for alias in (target.get('aliases') or []) if str(alias).strip())}\n\n"
        f"is_protagonist: {'Y' if bool(target.get('is_protagonist')) else 'N'}\n"
        f"is_first_person: {'Y' if bool(target.get('is_first_person')) else 'N'}\n\n"
        + (
            "inventory_context:\n"
            + "\n".join(inventory_lines)
            + "\n\n"
            if inventory_lines
            else ""
        )
        + (
            "relation_context:\n"
            + "\n".join(str(line).strip() for line in (relation_context_lines or []) if str(line).strip())
            + "\n\n"
            if relation_context_lines
            else ""
        )
        + (
            "summary_plan:\n"
            + "\n".join(
                f"- {line}"
                for line in [
                    *[str(value).strip() for value in (target.get("personality_hypothesis") or []) if str(value).strip()],
                    *[f"반응축: {str(value).strip()}" for value in (target.get("interaction_axes") or []) if str(value).strip()],
                    str(target.get("baseline_attitude_hypothesis") or "").strip(),
                    *[str(value).strip() for value in ((target.get("collection_rules") or {}).get("priority_patterns") or []) if str(value).strip()],
                ]
                if line
            )
            + "\n\n"
            if (
                target.get("personality_hypothesis")
                or target.get("interaction_axes")
                or target.get("baseline_attitude_hypothesis")
                or (target.get("collection_rules") or {}).get("priority_patterns")
            )
            else ""
        )
        + "아래는 원문에서 뽑은 실제 대사 모음이다.\n"
        + "\n".join(source_lines[:80])
        + (
            "\n\n아래는 episode_summary 발췌다. personality_core와 baseline_attitude 보조 근거로만 사용하라.\n"
            + "\n".join(f"- summary_context | {line}" for line in summary_context_lines[:8])
            if summary_context_lines
            else ""
        )
    )


def _string_list(value: object, *, limit: int = 8) -> list[str]:
    values = value if isinstance(value, list) else [value]
    result: list[str] = []
    for item in values:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text[:80])
        if len(result) >= limit:
            break
    return result


HONORIFIC_ADDRESS_SUFFIXES = (
    "님",
    "전하",
    "폐하",
    "공자",
    "공작",
    "궁주",
    "소궁주",
    "도련님",
    "아가씨",
    "사부",
    "사형",
    "장로",
    "노야",
    "교주",
    "각주",
    "선생님",
    "교수",
    "대장",
    "팀장",
    "대표님",
    "선배",
    "후배",
    "형님",
    "낭자",
    "헌터",
    "씨",
)


def _is_honorific_address_term(term: str) -> bool:
    text = str(term or "").strip()
    return bool(text) and text.endswith(HONORIFIC_ADDRESS_SUFFIXES)


def build_addressing_contract_v1(
    *,
    address_terms: list[str],
    forbidden_address_terms: list[str] | None = None,
    speech_register: str = "unknown",
) -> dict[str, object]:
    forbidden_terms: list[str] = []
    for value in forbidden_address_terms or []:
        _append_unique_text(forbidden_terms, str(value or ""), limit=8)

    allowed_terms: list[str] = []
    forbidden_set = set(forbidden_terms)
    for value in address_terms:
        text = str(value or "").strip()
        if text and text not in forbidden_set:
            _append_unique_text(allowed_terms, text, limit=8)

    has_honorific_surface = any(_is_honorific_address_term(term) for term in allowed_terms)
    if has_honorific_surface:
        distance_axis = "user_lower_or_formal_distance"
    else:
        distance_axis = "unknown"

    if allowed_terms and (has_honorific_surface or forbidden_terms):
        confidence = "high"
    elif allowed_terms:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "schema_version": "addressing_contract_v1",
        "user_to_character_allowed_calls": allowed_terms[:6],
        "user_to_character_forbidden_calls": forbidden_terms[:6],
        "character_to_user_default_call": "호칭 생략",
        "character_to_user_register": str(speech_register or "unknown"),
        "distance_axis": distance_axis,
        "switch_triggers": [
            "공개 호칭 근거가 있으면 공개 호칭을 우선한다",
            "금지 정체명은 reveal_boundary 전까지 먼저 쓰지 않는다",
        ],
        "evidence_terms": allowed_terms[:6],
        "confidence": confidence,
    }


def build_profile_voice_contract_v1(profile_payload: dict[str, object] | None) -> dict[str, object]:
    profile = dict(profile_payload or {})
    raw_speech_style = profile.get("speech_style") or {}
    speech_style = dict(raw_speech_style) if isinstance(raw_speech_style, dict) else {}
    formality = str(speech_style.get("formality") or "").strip()
    sentence_length = str(speech_style.get("sentence_length") or "").strip()
    address = str(speech_style.get("address") or "").strip()
    if "존대" in formality or "높임" in formality:
        speech_register = "formal_polite"
    elif "반말" in formality:
        speech_register = "casual"
    elif formality:
        speech_register = "mixed"
    else:
        speech_register = "unknown"

    if "짧" in sentence_length:
        default_sentence_length = "short"
    elif "장문" in sentence_length or "길" in sentence_length:
        default_sentence_length = "long"
    elif sentence_length:
        default_sentence_length = "medium"
    else:
        default_sentence_length = "unknown"

    address_terms = _string_list(address, limit=6)
    return {
        "schema_version": "voice_contract_v1",
        "stage": "rp_profile",
        "speech_register": speech_register,
        "default_sentence_length": default_sentence_length,
        "tone_keywords": _string_list(speech_style.get("tone"), limit=6),
        "habit_phrases": _string_list(speech_style.get("habit"), limit=6),
        "address_terms": address_terms,
        "addressing_contract_v1": build_addressing_contract_v1(
            address_terms=address_terms,
            speech_register=speech_register,
        ),
        "baseline_attitude": str(profile.get("baseline_attitude") or "").strip(),
        "forbidden_speech_patterns": [
            "무엇을 도와드릴까요",
            "안녕하세요",
            "제가 도와드릴게요",
            "작품에 대해 설명하자면",
        ],
    }


def build_character_chat_internal_prompt_user_prompt(
    *,
    target: dict[str, object],
    profile_payload: dict[str, object],
    example_payload: dict[str, object],
    dialogue_items: list[dict[str, object]],
    summary_context_lines: list[str],
    inventory_item: dict[str, object] | None = None,
    relation_context_lines: list[str] | None = None,
    scene_context_lines: list[str] | None = None,
) -> str:
    dialogue_lines: list[str] = []
    for item in dialogue_items[:40]:
        text_value = normalize_rp_text(str(item.get("text") or ""), limit=220)
        if not text_value:
            continue
        episode_no = int(item.get("episode_no") or 0)
        kind = str(item.get("kind") or "dialogue").strip()
        context = str(item.get("context") or "").strip()[:20]
        dialogue_lines.append(f"- {episode_no}화 | {kind} | {context} | {text_value}")

    example_lines = [
        f"- {int(item.get('episode_no') or 0)}화 | {normalize_rp_text(str(item.get('text') or ''), limit=220)}"
        for item in list(example_payload.get("examples") or [])[:5]
        if str(item.get("text") or "").strip()
    ]

    compact_inventory = {
        key: inventory_item.get(key)
        for key in [
            "display_name",
            "aliases",
            "is_protagonist",
            "is_first_person",
            "work_role",
            "identity_surface",
            "reveal_boundary",
            "read_range_state_snapshot",
            "interaction_affordance_v1",
            "adjacent_event_seed_v1",
            "pov_and_protagonist_centrality_v1",
            "voice_contract_v1",
            "chat_readiness_v1",
            "dominant_action_tags",
            "dominant_affect_tags",
            "relation_presence",
            "action_presence",
            "first_seen_episode_no",
            "distinct_episode_count",
        ]
        if inventory_item and inventory_item.get(key) not in (None, "", [])
    }
    profile_voice_contract = build_profile_voice_contract_v1(profile_payload)

    return (
        "[대상 캐릭터]\n"
        + json.dumps(
            {
                "display_name": str(target.get("display_name") or "").strip(),
                "aliases": [str(alias).strip() for alias in (target.get("aliases") or []) if str(alias).strip()],
                "is_protagonist": bool(target.get("is_protagonist")),
                "is_first_person": bool(target.get("is_first_person")),
            },
            ensure_ascii=False,
        )
        + "\n\n[인벤토리 근거]\n"
        + json.dumps(compact_inventory, ensure_ascii=False)
        + "\n\n[RP 프로필]\n"
        + json.dumps(profile_payload, ensure_ascii=False)
        + "\n\n[보이스 계약]\n"
        + json.dumps(
            {
                "profile_voice_contract": profile_voice_contract,
                "inventory_voice_contract": compact_inventory.get("voice_contract_v1") if compact_inventory else None,
            },
            ensure_ascii=False,
        )
        + "\n\n[대표 대사]\n"
        + ("\n".join(example_lines) if example_lines else "없음")
        + "\n\n[대사 후보]\n"
        + ("\n".join(dialogue_lines) if dialogue_lines else "없음")
        + "\n\n[회차 요약 근거]\n"
        + ("\n".join(f"- {line}" for line in summary_context_lines[:8]) if summary_context_lines else "없음")
        + "\n\n[관계 근거]\n"
        + ("\n".join(str(line).strip() for line in (relation_context_lines or [])[:8] if str(line).strip()) or "없음")
        + "\n\n[장면 프레임 근거]\n"
        + ("\n".join(str(line).strip() for line in (scene_context_lines or [])[:8] if str(line).strip()) or "없음")
        + "\n\n위 근거만 사용해 character_chat 내부 프롬프트를 작성하라."
    )


def split_text_lines(normalized_text: str) -> list[str]:
    return [re.sub(r"[ \t]+", " ", line).strip() for line in str(normalized_text or "").splitlines() if line.strip()]


def normalize_rp_text(value: str, *, limit: int = 300) -> str:
    cleaned = re.sub(r"\s+", " ", str(value or "").replace("\u3000", " ")).strip()
    return cleaned[:limit]


def _normalize_episode_scene_text_list(value, *, limit: int = 90, max_items: int = 4) -> list[str]:
    if value in (None, ""):
        return []
    raw_items = value if isinstance(value, list) else [value]
    items: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        if isinstance(item, dict):
            parts = [
                str(item.get(key) or "").strip()
                for key in ("choice", "trigger", "advance", "action", "item", "text")
                if str(item.get(key) or "").strip()
            ]
            text_value = " -> ".join(parts)
        else:
            text_value = str(item or "").strip()
        normalized = normalize_rp_text(text_value, limit=limit)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        items.append(normalized)
        if len(items) >= max_items:
            break
    return items


def _normalize_episode_scene_knowledge_boundary(value) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {"can_hint": [], "must_not_reveal": []}
    return {
        "can_hint": _normalize_episode_scene_text_list(value.get("can_hint"), limit=100, max_items=3),
        "must_not_reveal": _normalize_episode_scene_text_list(
            value.get("must_not_reveal"),
            limit=100,
            max_items=3,
        ),
    }


def _normalize_episode_scene_opening_grounding(value) -> dict[str, object]:
    if not isinstance(value, dict):
        return {
            "place_anchor": "",
            "sensory_anchors": [],
            "prop_anchors": [],
            "spatial_constraints": [],
            "character_visible_motion": "",
            "forbidden_opening_inventions": [],
        }
    return {
        "place_anchor": normalize_rp_text(str(value.get("place_anchor") or ""), limit=80),
        "sensory_anchors": _normalize_episode_scene_text_list(value.get("sensory_anchors"), limit=50, max_items=3),
        "prop_anchors": _normalize_episode_scene_text_list(value.get("prop_anchors"), limit=50, max_items=3),
        "spatial_constraints": _normalize_episode_scene_text_list(
            value.get("spatial_constraints"),
            limit=60,
            max_items=3,
        ),
        "character_visible_motion": normalize_rp_text(
            str(value.get("character_visible_motion") or ""),
            limit=100,
        ),
        "forbidden_opening_inventions": _normalize_episode_scene_text_list(
            value.get("forbidden_opening_inventions"),
            limit=50,
            max_items=3,
        ),
    }


def _normalize_episode_scene_identity_boundary(value) -> dict[str, object]:
    if not isinstance(value, dict):
        return {
            "allowed_address_names": [],
            "must_not_address_as": [],
            "surface_role_for_user": "",
            "identity_spoiler_risk": "unknown",
        }
    risk = str(value.get("identity_spoiler_risk") or "unknown").strip().lower()
    if risk not in {"low", "medium", "high", "unknown"}:
        risk = "unknown"
    return {
        "allowed_address_names": _normalize_episode_scene_text_list(
            value.get("allowed_address_names"),
            limit=40,
            max_items=4,
        ),
        "must_not_address_as": _normalize_episode_scene_text_list(
            value.get("must_not_address_as"),
            limit=50,
            max_items=4,
        ),
        "surface_role_for_user": normalize_rp_text(str(value.get("surface_role_for_user") or ""), limit=80),
        "identity_spoiler_risk": risk,
    }


def _normalize_episode_scene_response_branches(value) -> dict[str, str]:
    if not isinstance(value, dict):
        value = {}
    branch_keys = (
        "accepts_hook",
        "asks_question",
        "refuses_or_delays",
        "short_or_ambiguous",
        "hostile_or_suspicious",
    )
    return {
        key: normalize_rp_text(str(value.get(key) or ""), limit=100)
        for key in branch_keys
    }


def _normalize_episode_scene_turn_contract(value) -> dict[str, object]:
    if not isinstance(value, dict):
        return {
            "state_variables": [],
            "user_response_branches": _normalize_episode_scene_response_branches({}),
            "stall_breaker": "",
            "scene_exit_condition": "",
            "canon_safe_new_event_types": [],
        }
    return {
        "state_variables": _normalize_episode_scene_text_list(value.get("state_variables"), limit=70, max_items=4),
        "user_response_branches": _normalize_episode_scene_response_branches(
            value.get("user_response_branches")
        ),
        "stall_breaker": normalize_rp_text(str(value.get("stall_breaker") or ""), limit=100),
        "scene_exit_condition": normalize_rp_text(str(value.get("scene_exit_condition") or ""), limit=100),
        "canon_safe_new_event_types": _normalize_episode_scene_text_list(
            value.get("canon_safe_new_event_types"),
            limit=50,
            max_items=4,
        ),
    }


def _is_usable_episode_scene_payload(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    if str(payload.get("status") or "").strip().lower() not in {"ok", "partial"}:
        return False
    scene_count = payload.get("scene_count")
    if not isinstance(scene_count, int) or isinstance(scene_count, bool):
        return False
    scenes = payload.get("scenes")
    if scene_count <= 0 or not isinstance(scenes, list) or not scenes:
        return False
    first_scene = scenes[0]
    return isinstance(first_scene, dict) and bool(str(first_scene.get("scene_gist") or "").strip())


EPISODE_SCENE_KIND_VALUES = {"dialogue", "action", "conflict", "exposition", "transition", "mixed"}
EPISODE_SCENE_STATUS_VALUES = {"ok", "partial", "failed"}


def build_line_indexed_episode_text(normalized_text: str) -> tuple[str, list[dict[str, object]]]:
    """원문 line/char offset을 모델 입력에 노출한다. 판정은 이 map으로만 한다."""
    rows: list[dict[str, object]] = []
    offset = 0
    for line_no, raw_line in enumerate(str(normalized_text or "").splitlines(keepends=True), start=1):
        line_text = raw_line.rstrip("\r\n")
        line_start = offset
        line_end = line_start + len(line_text)
        offset += len(raw_line)
        compact_line = re.sub(r"[ \t]+", " ", line_text).strip()
        if not compact_line:
            continue
        rows.append(
            {
                "line_no": line_no,
                "char_start": line_start,
                "char_end": line_end,
                "text": compact_line,
            }
        )
    indexed_text = "\n".join(
        f"L{int(row['line_no']):04d}|{int(row['char_start'])}-{int(row['char_end'])}| {row['text']}"
        for row in rows
    )
    return indexed_text, rows


def _collapse_episode_scene_anchor_text(value: str) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def _build_episode_scene_collapsed_index(value: str) -> tuple[str, list[int]]:
    chars: list[str] = []
    positions: list[int] = []
    for index, char in enumerate(str(value or "")):
        if char.isspace():
            continue
        chars.append(char)
        positions.append(index)
    return "".join(chars), positions


def resolve_episode_scene_anchor(
    normalized_text: str,
    anchor_text: str,
    *,
    start_after: int = 0,
) -> dict[str, object] | None:
    source_text = str(normalized_text or "")
    anchor = str(anchor_text or "").strip()
    if not source_text or not anchor:
        return None

    exact_start = source_text.find(anchor, max(0, start_after))
    if exact_start >= 0:
        exact_end = exact_start + len(anchor)
        return {
            "char_start": exact_start,
            "char_end": exact_end,
            "matched_text": source_text[exact_start:exact_end],
            "match_type": "exact",
        }

    collapsed_anchor = _collapse_episode_scene_anchor_text(anchor)
    if len(collapsed_anchor) < 4:
        return None
    collapsed_source, positions = _build_episode_scene_collapsed_index(source_text)
    collapsed_start = 0
    while collapsed_start < len(positions) and positions[collapsed_start] < start_after:
        collapsed_start += 1
    collapsed_found = collapsed_source.find(collapsed_anchor, collapsed_start)
    if collapsed_found < 0:
        return None
    char_start = positions[collapsed_found]
    char_end = positions[collapsed_found + len(collapsed_anchor) - 1] + 1
    return {
        "char_start": char_start,
        "char_end": char_end,
        "matched_text": source_text[char_start:char_end],
        "match_type": "whitespace_normalized",
    }


def _episode_scene_line_no_for_offset(line_rows: list[dict[str, object]], offset: int) -> int:
    if not line_rows:
        return 0
    safe_offset = max(0, int(offset))
    previous_line_no = int(line_rows[0].get("line_no") or 0)
    for row in line_rows:
        line_no = int(row.get("line_no") or 0)
        line_start = int(row.get("char_start") or 0)
        line_end = int(row.get("char_end") or line_start)
        if safe_offset < line_start:
            return previous_line_no
        if line_start <= safe_offset <= max(line_start, line_end):
            return line_no
        previous_line_no = line_no
    return int(line_rows[-1].get("line_no") or 0)


def _build_episode_scene_canonical_map(canonical_character_packet: object | None) -> dict[str, dict[str, object]]:
    if isinstance(canonical_character_packet, dict):
        raw_items = canonical_character_packet.get("characters") or canonical_character_packet.get("items") or []
    elif isinstance(canonical_character_packet, list):
        raw_items = canonical_character_packet
    else:
        raw_items = []

    canonical_by_scope: dict[str, dict[str, object]] = {}
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        scope_key = str(
            raw_item.get("scope_key")
            or raw_item.get("scopeKey")
            or raw_item.get("canonical_character_key")
            or raw_item.get("character_key")
            or ""
        ).strip()
        if not scope_key:
            continue
        display_name = str(raw_item.get("display_name") or raw_item.get("displayName") or "").strip()
        aliases = [str(alias).strip() for alias in (raw_item.get("aliases") or []) if str(alias).strip()]
        canonical_by_scope[scope_key] = {"scope_key": scope_key, "display_name": display_name, "aliases": aliases}
    return canonical_by_scope


def _normalize_episode_scene_participants(
    raw_participants: object,
    canonical_by_scope: dict[str, dict[str, object]],
    validation_issues: list[str],
    scene_index: int,
) -> list[dict[str, object]]:
    participants: list[dict[str, object]] = []
    if not isinstance(raw_participants, list):
        return participants
    for participant_index, raw_participant in enumerate(raw_participants[:12], start=1):
        if not isinstance(raw_participant, dict):
            continue
        mention_label = normalize_rp_text(
            str(
                raw_participant.get("mention_label")
                or raw_participant.get("display_name")
                or raw_participant.get("name")
                or ""
            ),
            limit=40,
        )
        scope_key = str(raw_participant.get("scope_key") or raw_participant.get("scopeKey") or "").strip()
        if scope_key and scope_key not in canonical_by_scope:
            validation_issues.append(f"scene_{scene_index}_participant_{participant_index}_unknown_scope:{scope_key}")
            scope_key = ""
        evidence = normalize_rp_text(str(raw_participant.get("evidence") or ""), limit=120)
        if not mention_label and not scope_key:
            continue
        normalized_item: dict[str, object] = {
            "mention_label": mention_label or canonical_by_scope.get(scope_key, {}).get("display_name") or "",
            "scope_key": scope_key or None,
        }
        if scope_key:
            normalized_item["display_name"] = str(canonical_by_scope[scope_key].get("display_name") or "")
        if evidence:
            normalized_item["evidence"] = evidence
        participants.append(normalized_item)
    return participants


def _normalize_episode_scene_action_ownership(
    raw_actions: object,
    canonical_by_scope: dict[str, dict[str, object]],
    validation_issues: list[str],
    scene_index: int,
) -> list[dict[str, object]]:
    actions: list[dict[str, object]] = []
    if not isinstance(raw_actions, list):
        return actions
    for action_index, raw_action in enumerate(raw_actions[:12], start=1):
        if not isinstance(raw_action, dict):
            continue
        action = normalize_rp_text(str(raw_action.get("action") or ""), limit=100)
        if not action:
            continue
        actor_scope_key = str(raw_action.get("actor_scope_key") or raw_action.get("scope_key") or "").strip()
        if actor_scope_key and actor_scope_key not in canonical_by_scope:
            validation_issues.append(f"scene_{scene_index}_action_{action_index}_unknown_scope:{actor_scope_key}")
            actor_scope_key = ""
        actions.append({"actor_scope_key": actor_scope_key or None, "action": action})
    return actions


def normalize_episode_scene_extraction_payload(
    payload: dict | None,
    *,
    normalized_text: str,
    canonical_character_packet: object | None = None,
    episode_no: int = 0,
) -> dict[str, object]:
    source_text = str(normalized_text or "")[:EPISODE_SCENE_EXTRACTION_MAX_INPUT_CHARS]
    _, line_rows = build_line_indexed_episode_text(source_text)
    canonical_by_scope = _build_episode_scene_canonical_map(canonical_character_packet)
    validation_issues: list[str] = []
    if not isinstance(payload, dict):
        return {
            "schema_version": EPISODE_SCENE_EXTRACTION_FORMAT_VERSION,
            "episode_no": int(episode_no or 0),
            "status": "failed",
            "scene_count": 0,
            "dropped_scene_count": 0,
            "validation_issues": ["payload_not_object"],
            "scenes": [],
        }

    raw_scenes = payload.get("scenes") or []
    if not isinstance(raw_scenes, list):
        raw_scenes = []
        validation_issues.append("scenes_not_list")

    resolved_scenes: list[dict[str, object]] = []
    search_cursor = 0
    dropped_scene_count = 0
    for raw_index, raw_scene in enumerate(raw_scenes[:12], start=1):
        if not isinstance(raw_scene, dict):
            dropped_scene_count += 1
            validation_issues.append(f"scene_{raw_index}_not_object")
            continue
        anchor = str(
            raw_scene.get("boundary_anchor_start")
            or raw_scene.get("start_anchor")
            or raw_scene.get("anchor")
            or ""
        ).strip()
        match = resolve_episode_scene_anchor(source_text, anchor, start_after=search_cursor)
        if match is None:
            match = resolve_episode_scene_anchor(source_text, anchor, start_after=0)
        if match is None:
            dropped_scene_count += 1
            validation_issues.append(f"scene_{raw_index}_anchor_not_found")
            continue
        search_cursor = max(search_cursor, int(match["char_end"]))
        scene_kind = str(raw_scene.get("scene_kind") or "mixed").strip().lower()
        if scene_kind not in EPISODE_SCENE_KIND_VALUES:
            validation_issues.append(f"scene_{raw_index}_unknown_kind:{scene_kind}")
            scene_kind = "mixed"
        resolved_scenes.append(
            {
                "raw_index": raw_index,
                "boundary_anchor_start": anchor,
                "scene_kind": scene_kind,
                "scene_gist": normalize_rp_text(str(raw_scene.get("scene_gist") or ""), limit=160),
                "current_action": normalize_rp_text(str(raw_scene.get("current_action") or ""), limit=120),
                "immediate_pressure": normalize_rp_text(str(raw_scene.get("immediate_pressure") or ""), limit=120),
                "character_initiative_reason": normalize_rp_text(
                    str(raw_scene.get("character_initiative_reason") or ""),
                    limit=140,
                ),
                "user_entry_role": normalize_rp_text(str(raw_scene.get("user_entry_role") or ""), limit=80),
                "user_hook": normalize_rp_text(str(raw_scene.get("user_hook") or ""), limit=140),
                "user_can_do": _normalize_episode_scene_text_list(
                    raw_scene.get("user_can_do"),
                    limit=90,
                    max_items=4,
                ),
                "opening_grounding": _normalize_episode_scene_opening_grounding(
                    raw_scene.get("opening_grounding")
                ),
                "scene_identity_boundary": _normalize_episode_scene_identity_boundary(
                    raw_scene.get("scene_identity_boundary")
                ),
                "pressure_clock": normalize_rp_text(str(raw_scene.get("pressure_clock") or ""), limit=140),
                "conversation_fuel_tags": _normalize_episode_scene_text_list(
                    raw_scene.get("conversation_fuel_tags"),
                    limit=40,
                    max_items=3,
                ),
                "beat_ladder": _normalize_episode_scene_text_list(
                    raw_scene.get("beat_ladder"),
                    limit=140,
                    max_items=4,
                ),
                "turn_continuation_contract": _normalize_episode_scene_turn_contract(
                    raw_scene.get("turn_continuation_contract")
                ),
                "knowledge_boundary": _normalize_episode_scene_knowledge_boundary(
                    raw_scene.get("knowledge_boundary")
                ),
                "progression_seed": normalize_rp_text(str(raw_scene.get("progression_seed") or ""), limit=140),
                "participants": _normalize_episode_scene_participants(
                    raw_scene.get("participants"),
                    canonical_by_scope,
                    validation_issues,
                    raw_index,
                ),
                "action_ownership": _normalize_episode_scene_action_ownership(
                    raw_scene.get("action_ownership"),
                    canonical_by_scope,
                    validation_issues,
                    raw_index,
                ),
                "char_start": int(match["char_start"]),
                "anchor_end": int(match["char_end"]),
                "anchor_match": {
                    "type": str(match.get("match_type") or ""),
                    "text": normalize_rp_text(str(match.get("matched_text") or ""), limit=120),
                },
            }
        )

    resolved_scenes.sort(key=lambda item: (int(item["char_start"]), int(item["raw_index"])))
    deduped_scenes: list[dict[str, object]] = []
    seen_starts: set[int] = set()
    for scene in resolved_scenes:
        char_start = int(scene["char_start"])
        if char_start in seen_starts:
            dropped_scene_count += 1
            validation_issues.append(f"scene_{int(scene['raw_index'])}_duplicate_anchor")
            continue
        seen_starts.add(char_start)
        deduped_scenes.append(scene)

    normalized_scenes: list[dict[str, object]] = []
    for index, scene in enumerate(deduped_scenes, start=1):
        char_start = int(scene["char_start"])
        next_start = (
            int(deduped_scenes[index]["char_start"])
            if index < len(deduped_scenes)
            else len(source_text)
        )
        char_end = max(int(scene["anchor_end"]), next_start)
        normalized_scenes.append(
            {
                "scene_index": index,
                "boundary_anchor_start": scene["boundary_anchor_start"],
                "scene_kind": scene["scene_kind"],
                "scene_gist": scene["scene_gist"],
                "current_action": scene["current_action"],
                "immediate_pressure": scene["immediate_pressure"],
                "character_initiative_reason": scene["character_initiative_reason"],
                "user_entry_role": scene["user_entry_role"],
                "user_hook": scene["user_hook"],
                "user_can_do": scene["user_can_do"],
                "opening_grounding": scene["opening_grounding"],
                "scene_identity_boundary": scene["scene_identity_boundary"],
                "pressure_clock": scene["pressure_clock"],
                "conversation_fuel_tags": scene["conversation_fuel_tags"],
                "beat_ladder": scene["beat_ladder"],
                "turn_continuation_contract": scene["turn_continuation_contract"],
                "knowledge_boundary": scene["knowledge_boundary"],
                "progression_seed": scene["progression_seed"],
                "participants": scene["participants"],
                "action_ownership": scene["action_ownership"],
                "start_line": _episode_scene_line_no_for_offset(line_rows, char_start),
                "end_line": _episode_scene_line_no_for_offset(line_rows, max(char_start, char_end - 1)),
                "char_start": char_start,
                "char_end": char_end,
                "anchor_match": scene["anchor_match"],
            }
        )

    raw_status = str(payload.get("status") or "ok").strip().lower()
    if raw_status not in EPISODE_SCENE_STATUS_VALUES:
        validation_issues.append(f"unknown_status:{raw_status}")
        raw_status = "partial"
    if not normalized_scenes:
        status = "failed"
    elif dropped_scene_count or validation_issues or raw_status != "ok":
        status = "partial"
    else:
        status = "ok"

    return {
        "schema_version": EPISODE_SCENE_EXTRACTION_FORMAT_VERSION,
        "episode_no": int(episode_no or 0),
        "status": status,
        "scene_count": len(normalized_scenes),
        "dropped_scene_count": dropped_scene_count,
        "validation_issues": validation_issues[:40],
        "scenes": normalized_scenes,
    }


def build_episode_scene_extraction_user_prompt(
    *,
    product_title: str,
    episode_no: int,
    episode_title: str,
    normalized_text: str,
    canonical_character_packet: object | None = None,
) -> str:
    source_text = str(normalized_text or "")[:EPISODE_SCENE_EXTRACTION_MAX_INPUT_CHARS]
    indexed_text, _ = build_line_indexed_episode_text(source_text)
    return (
        "[작품]\n"
        + json.dumps(
            {
                "product_title": str(product_title or "").strip(),
                "episode_no": int(episode_no or 0),
                "episode_title": str(episode_title or "").strip(),
                "schema_version": EPISODE_SCENE_EXTRACTION_FORMAT_VERSION,
            },
            ensure_ascii=False,
        )
        + "\n\n[canonical_character_packet]\n"
        + json.dumps(canonical_character_packet or {"characters": []}, ensure_ascii=False)
        + "\n\n[회차 원문: 라인/문자 오프셋 포함]\n"
        + (indexed_text or "원문 없음")
        + "\n\n위 원문에서 캐릭터챗 재료로 쓸 장면만 추출하라. boundary_anchor_start는 반드시 원문 일부를 그대로 사용하라."
    )


def build_rp_context(line: str, prev_line: str = "") -> str:
    source = normalize_rp_text(prev_line or line, limit=40)
    return source[:20]


def extract_dialogue_segments(normalized_text: str) -> list[dict[str, str]]:
    lines = split_text_lines(normalized_text)
    items: list[dict[str, str]] = []
    for idx, line in enumerate(lines):
        prev_line = lines[idx - 1] if idx > 0 else ""
        next_line = lines[idx + 1] if idx + 1 < len(lines) else ""
        for match in DIALOGUE_QUOTE_RE.finditer(line):
            text_value = normalize_rp_text(match.group(1), limit=300)
            if len(text_value) < 2:
                continue
            pre_quote = normalize_rp_text(line[:match.start()], limit=160)
            post_quote = normalize_rp_text(line[match.end():], limit=160)
            items.append(
                {
                    "kind": "dialogue",
                    "context": build_rp_context(line, prev_line),
                    "text": text_value,
                    "line": normalize_rp_text(line, limit=300),
                    "prev_line": normalize_rp_text(prev_line, limit=240),
                    "pre_quote": pre_quote,
                    "post_quote": post_quote,
                    "speaker_hint": normalize_rp_text(f"{prev_line} {line} {next_line}", limit=240),
                }
            )
    return items


def extract_first_person_monologues(normalized_text: str) -> list[dict[str, str]]:
    lines = split_text_lines(normalized_text)
    items: list[dict[str, str]] = []
    for idx, line in enumerate(lines):
        if '"' in line or '“' in line or '”' in line:
            continue
        text_value = normalize_rp_text(line, limit=300)
        if len(text_value) < 6:
            continue
        if not FIRST_PERSON_MONOLOGUE_RE.search(text_value):
            continue
        prev_line = lines[idx - 1] if idx > 0 else ""
        items.append(
            {
                "kind": "monologue",
                "context": build_rp_context(line, prev_line),
                "text": text_value,
                "speaker_hint": normalize_rp_text(f"{prev_line} {line}", limit=240),
            }
        )
    return items


def has_speaker_anchor_match(
    hint: str,
    speaker_anchors: list[str],
    *,
    allow_single_char_anchors: bool = False,
) -> bool:
    source = str(hint or "")
    for anchor in speaker_anchors:
        anchor_text = str(anchor or "").strip()
        if len(anchor_text) < SPEAKER_ANCHOR_MIN_CHARS and not allow_single_char_anchors:
            continue
        pattern = (
            rf"(?<![가-힣A-Za-z0-9])"
            rf"{re.escape(anchor_text)}"
            rf"{KOREAN_NAME_PARTICLE_PATTERN}"
            rf"(?![가-힣A-Za-z0-9])"
        )
        if re.search(pattern, source):
            return True
    return False


def _speaker_subject_pattern(anchor_text: str) -> str:
    return (
        rf"(?<![가-힣A-Za-z0-9])"
        rf"{re.escape(anchor_text)}"
        rf"(?:은|는|이|가|도|만)?"
        rf"(?![가-힣A-Za-z0-9])"
    )


def _is_bare_quote_line(item: dict[str, object]) -> bool:
    line = str(item.get("line") or "")
    without_quotes = DIALOGUE_QUOTE_RE.sub("", line)
    return not re.sub(r"[\s,.'\"“”!?…~:;·-]+", "", without_quotes)


def find_attributed_speaker_anchors(
    item: dict[str, object],
    speaker_anchors: list[str],
    *,
    allow_single_char_anchors: bool = False,
) -> list[str]:
    contexts = [
        str(item.get("pre_quote") or ""),
        str(item.get("post_quote") or ""),
    ]
    if _is_bare_quote_line(item):
        contexts.append(str(item.get("prev_line") or ""))

    matched: list[str] = []
    for anchor in speaker_anchors:
        anchor_text = str(anchor or "").strip()
        if len(anchor_text) < SPEAKER_ANCHOR_MIN_CHARS and not allow_single_char_anchors:
            continue
        subject_pattern = _speaker_subject_pattern(anchor_text)
        attribution_pattern = rf"{subject_pattern}.{{0,48}}{SPEECH_VERB_PATTERN}"
        if any(re.search(attribution_pattern, context) for context in contexts):
            if anchor_text not in matched:
                matched.append(anchor_text)
    return matched


def is_dialogue_attributed_to_target(
    item: dict[str, object],
    speaker_anchors: list[str],
    *,
    competing_speaker_anchors: list[str] | None = None,
    allow_single_char_anchors: bool = False,
) -> bool:
    target_matches = find_attributed_speaker_anchors(
        item,
        speaker_anchors,
        allow_single_char_anchors=allow_single_char_anchors,
    )
    if not target_matches:
        return False
    competitor_matches = find_attributed_speaker_anchors(
        item,
        [
            anchor
            for anchor in list(competing_speaker_anchors or [])
            if str(anchor or "").strip() not in set(target_matches)
        ],
        allow_single_char_anchors=True,
    )
    return not competitor_matches


def collect_rule_based_rp_dialogue_items(target: dict[str, object], normalized_text: str) -> list[dict[str, object]]:
    collection_rules = target.get("collection_rules") or {}
    use_dialogue = bool(collection_rules.get("use_dialogue", True))
    use_monologue = bool(collection_rules.get("use_monologue", False))
    speaker_anchors = [str(anchor).strip() for anchor in (collection_rules.get("speaker_anchors") or target.get("aliases") or []) if str(anchor).strip()]
    competing_speaker_anchors = [str(anchor).strip() for anchor in (collection_rules.get("competing_speaker_anchors") or []) if str(anchor).strip()]
    exclude_tokens = [str(token).strip() for token in (collection_rules.get("exclude_tokens") or []) if str(token).strip()]
    allow_single_char_anchors = len(str(target.get("display_name") or "").strip()) == 1

    dialogue_segments = extract_dialogue_segments(normalized_text)
    matched: list[dict[str, object]] = []
    if use_dialogue and speaker_anchors:
        for item in dialogue_segments:
            hint = str(item.get("speaker_hint") or "")
            if exclude_tokens and any(token in hint for token in exclude_tokens):
                continue
            if is_dialogue_attributed_to_target(
                item,
                speaker_anchors,
                competing_speaker_anchors=competing_speaker_anchors,
                allow_single_char_anchors=allow_single_char_anchors,
            ):
                matched.append(item)
    if bool(target.get("is_protagonist")) and bool(target.get("is_first_person")) and use_monologue:
        matched.extend(extract_first_person_monologues(normalized_text))
    return matched


def dedupe_rp_dialogue_items(items: list[dict[str, object]], limit: int = 80) -> list[dict[str, object]]:
    deduped: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        kind = str(item.get("kind") or "dialogue").strip().lower() or "dialogue"
        text_value = normalize_rp_text(str(item.get("text") or ""), limit=300)
        if len(text_value) < 2:
            continue
        key = (kind, text_value)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(
            {
                "kind": kind,
                "context": normalize_rp_text(str(item.get("context") or ""), limit=20),
                "text": text_value,
                "episode_no": int(item.get("episode_no") or 0),
            }
        )
        if len(deduped) >= limit:
            break
    return deduped


def _strip_vocative_suffix(text_value: str) -> str:
    base = re.sub(r"[!?.…~\s]+$", "", str(text_value or "").strip())
    if base.endswith(("아", "야")):
        return base[:-1]
    return base


def is_viable_rp_example_text(text_value: str, aliases: list[str]) -> bool:
    normalized = normalize_rp_text(text_value, limit=300)
    if len(normalized) < 6:
        return False
    if RP_NOISE_ONLY_RE.fullmatch(normalized):
        return False
    if RP_SIMPLE_VOCATIVE_RE.fullmatch(normalized):
        base = _strip_vocative_suffix(normalized)
        if any(_strip_vocative_suffix(alias) == base for alias in aliases if alias):
            return False
        if " " not in normalized:
            return False
    token_count = len([token for token in normalized.split(" ") if token])
    if token_count <= 2 and len(normalized) <= 10:
        return False
    return True


def score_rp_example_text(text_value: str, aliases: list[str]) -> int:
    normalized = normalize_rp_text(text_value, limit=300)
    if not is_viable_rp_example_text(normalized, aliases):
        return -1
    token_count = len([token for token in normalized.split(" ") if token])
    score = min(token_count * 2, 10)
    if len(normalized) >= 12:
        score += 1
    if len(normalized) >= 20:
        score += 1
    if any(mark in normalized for mark in ("?", "!", "…", "~")):
        score += 1
    if any(mark in normalized for mark in (",", "니까", "잖아", "거든", "군", "죠")):
        score += 1
    return score


def is_preferred_rp_example_text(text_value: str, aliases: list[str]) -> bool:
    return score_rp_example_text(text_value, aliases) >= 5


def mark_rp_example_candidates(items: list[dict[str, object]], aliases: list[str]) -> list[dict[str, object]]:
    marked: list[dict[str, object]] = []
    for item in items:
        copied = dict(item)
        example_score = (
            score_rp_example_text(str(copied.get("text") or ""), aliases)
            if str(copied.get("kind") or "dialogue").strip().lower() == "dialogue"
            else -1
        )
        copied["example_score"] = example_score
        copied["is_example_candidate"] = example_score >= 5
        marked.append(copied)
    return marked


def build_voice_evidence_stats(items: list[dict[str, object]], aliases: list[str]) -> dict[str, object]:
    marked_items = mark_rp_example_candidates(dedupe_rp_dialogue_items(items, limit=200), aliases)
    episode_counts = Counter(
        int(item.get("episode_no") or 0)
        for item in marked_items
        if int(item.get("episode_no") or 0) > 0
    )
    item_count = len(marked_items)
    total_chars = sum(len(str(item.get("text") or "")) for item in marked_items)
    example_count = sum(1 for item in marked_items if bool(item.get("is_example_candidate")))
    max_episode_share = (
        max(episode_counts.values()) / item_count
        if item_count and episode_counts
        else 0.0
    )
    return {
        "item_count": item_count,
        "episode_count": len(episode_counts),
        "total_chars": total_chars,
        "example_count": example_count,
        "max_episode_share": round(max_episode_share, 4),
        "sample_texts": [
            str(item.get("text") or "")
            for item in marked_items[:5]
            if str(item.get("text") or "")
        ],
    }


def build_direct_voice_evidence_quality(
    target: dict[str, object],
    episode_texts_by_no: dict[int, str],
) -> dict[str, object]:
    aliases: list[str] = []
    for alias in [target.get("display_name"), *list(target.get("aliases") or [])]:
        alias_text = str(alias or "").strip()
        if alias_text and alias_text not in aliases:
            aliases.append(alias_text)
    if is_generic_character_label(str(target.get("display_name") or "")) and not _target_allows_role_like_persona_display(target):
        empty_stats = build_voice_evidence_stats([], aliases)
        return {
            "status": "excluded_generic_label",
            "strict_chat_ready": False,
            "dialogue": empty_stats,
            "monologue": empty_stats,
        }
    dialogue_target = dict(target)
    dialogue_rules = dict(dialogue_target.get("collection_rules") or {})
    dialogue_rules["use_dialogue"] = True
    dialogue_rules["use_monologue"] = False
    dialogue_target["collection_rules"] = dialogue_rules
    dialogue_target["is_first_person"] = False

    dialogue_items: list[dict[str, object]] = []
    monologue_items: list[dict[str, object]] = []
    is_first_person = bool(target.get("is_protagonist")) and bool(target.get("is_first_person"))
    for episode_no in sorted(episode_texts_by_no.keys()):
        normalized_text = str(episode_texts_by_no.get(episode_no) or "")
        if not normalized_text:
            continue
        for item in collect_rule_based_rp_dialogue_items(dialogue_target, normalized_text):
            copied = dict(item)
            copied["episode_no"] = episode_no
            dialogue_items.append(copied)
        if is_first_person:
            for item in extract_first_person_monologues(normalized_text):
                copied = dict(item)
                copied["episode_no"] = episode_no
                monologue_items.append(copied)

    dialogue_stats = build_voice_evidence_stats(dialogue_items, aliases)
    monologue_stats = build_voice_evidence_stats(monologue_items, aliases)
    dialogue_ready = (
        int(dialogue_stats["item_count"]) >= DIRECT_VOICE_DIALOGUE_MIN_ITEMS
        and int(dialogue_stats["episode_count"]) >= DIRECT_VOICE_DIALOGUE_MIN_EPISODES
        and int(dialogue_stats["total_chars"]) >= DIRECT_VOICE_DIALOGUE_MIN_CHARS
        and int(dialogue_stats["example_count"]) >= DIRECT_VOICE_DIALOGUE_MIN_EXAMPLES
        and float(dialogue_stats["max_episode_share"]) <= DIRECT_VOICE_MAX_EPISODE_SHARE
    )
    monologue_ready = (
        is_first_person
        and int(monologue_stats["item_count"]) >= DIRECT_VOICE_MONOLOGUE_MIN_ITEMS
        and int(monologue_stats["episode_count"]) >= DIRECT_VOICE_MONOLOGUE_MIN_EPISODES
        and int(monologue_stats["total_chars"]) >= DIRECT_VOICE_MONOLOGUE_MIN_CHARS
        and float(monologue_stats["max_episode_share"]) <= DIRECT_VOICE_MAX_EPISODE_SHARE
    )
    if dialogue_ready:
        status = "strict_dialogue_ready"
    elif monologue_ready:
        status = "strict_monologue_ready"
    elif int(dialogue_stats["item_count"]) or int(monologue_stats["item_count"]):
        status = "direct_limited"
    else:
        status = "insufficient"
    return {
        "status": status,
        "strict_chat_ready": bool(dialogue_ready or monologue_ready),
        "dialogue": dialogue_stats,
        "monologue": monologue_stats,
    }


def is_strict_dialogue_item_set_ready(items: list[dict[str, object]], aliases: list[str]) -> bool:
    stats = build_voice_evidence_stats(items, aliases)
    return (
        int(stats["item_count"]) >= DIRECT_VOICE_DIALOGUE_MIN_ITEMS
        and int(stats["episode_count"]) >= DIRECT_VOICE_DIALOGUE_MIN_EPISODES
        and int(stats["total_chars"]) >= DIRECT_VOICE_DIALOGUE_MIN_CHARS
        and int(stats["example_count"]) >= DIRECT_VOICE_DIALOGUE_MIN_EXAMPLES
        and float(stats["max_episode_share"]) <= DIRECT_VOICE_MAX_EPISODE_SHARE
    )


def collect_rule_based_rp_dialogue_items_by_episode(
    target: dict[str, object],
    episode_texts_by_no: dict[int, str],
) -> list[dict[str, object]]:
    dialogue_items: list[dict[str, object]] = []
    priority_episode_nos = [int(no) for no in (target.get("evidence_episodes") or []) if int(no) in episode_texts_by_no]
    remaining_episode_nos = [
        int(no)
        for no in sorted(episode_texts_by_no.keys())
        if int(no) not in set(priority_episode_nos)
    ]
    for episode_no in priority_episode_nos + remaining_episode_nos:
        normalized_text = str(episode_texts_by_no.get(episode_no) or "")
        if not normalized_text:
            continue
        extracted_items = collect_rule_based_rp_dialogue_items(target, normalized_text)
        for item in extracted_items:
            item["episode_no"] = episode_no
            dialogue_items.append(item)
    return dialogue_items


def score_rp_dialogue_fallback_episode(text: str, aliases: list[str]) -> int:
    quote_count = len(DIALOGUE_QUOTE_RE.findall(str(text or "")))
    if quote_count <= 0:
        return 0
    alias_count = sum(str(text or "").count(alias) for alias in aliases if alias)
    return (100 if alias_count else 0) + min(alias_count, 8) * 8 + min(quote_count, 18)


def build_rp_dialogue_fallback_excerpt(text: str, aliases: list[str]) -> str:
    source = str(text or "")
    if len(source) <= RP_DIALOGUE_FALLBACK_EXCERPT_CHARS:
        return source
    positions: list[int] = []
    for alias in aliases:
        start = 0
        while alias:
            index = source.find(alias, start)
            if index < 0:
                break
            positions.append(index)
            start = index + max(1, len(alias))
    if not positions:
        positions = [match.start() for match in list(DIALOGUE_QUOTE_RE.finditer(source))[:30]]
    if not positions:
        return source[:RP_DIALOGUE_FALLBACK_EXCERPT_CHARS]

    best_start = 0
    best_score = -1
    half_window = RP_DIALOGUE_FALLBACK_EXCERPT_CHARS // 2
    for position in positions[:100]:
        start = max(0, position - half_window)
        end = min(len(source), start + RP_DIALOGUE_FALLBACK_EXCERPT_CHARS)
        start = max(0, end - RP_DIALOGUE_FALLBACK_EXCERPT_CHARS)
        excerpt = source[start:end]
        score = score_rp_dialogue_fallback_episode(excerpt, aliases)
        if score > best_score:
            best_score = score
            best_start = start
    return source[best_start : best_start + RP_DIALOGUE_FALLBACK_EXCERPT_CHARS]


def build_rp_dialogue_fallback_input(
    target: dict[str, object],
    episode_texts_by_no: dict[int, str],
    aliases: list[str],
) -> str:
    scored_episode_nos: list[tuple[int, int]] = []
    priority_episode_nos = [int(no) for no in (target.get("evidence_episodes") or []) if int(no) in episode_texts_by_no]
    remaining_episode_nos = [
        int(no)
        for no in sorted(episode_texts_by_no.keys())
        if int(no) not in set(priority_episode_nos)
    ]
    for episode_no in priority_episode_nos + remaining_episode_nos:
        score = score_rp_dialogue_fallback_episode(str(episode_texts_by_no.get(episode_no) or ""), aliases)
        if score > 0:
            scored_episode_nos.append((score, episode_no))
    episode_nos = [
        episode_no
        for _, episode_no in sorted(scored_episode_nos, key=lambda item: (-item[0], item[1]))[:RP_DIALOGUE_FALLBACK_MAX_EPISODES]
    ]
    blocks = []
    for episode_no in episode_nos:
        excerpt = build_rp_dialogue_fallback_excerpt(str(episode_texts_by_no.get(episode_no) or ""), aliases)
        if excerpt:
            blocks.append(f'<episode no="{episode_no}">\n{excerpt}\n</episode>')
    return "\n".join(blocks)


def validate_llm_rp_dialogue_items(
    raw_items: list[dict[str, object]],
    episode_texts_by_no: dict[int, str],
) -> list[dict[str, object]]:
    valid_items: list[dict[str, object]] = []
    seen: set[tuple[int, str]] = set()
    per_episode_counts: Counter[int] = Counter()
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        try:
            episode_no = int(item.get("episode_no") or 0)
            confidence = float(item.get("confidence") or 0.0)
        except (TypeError, ValueError):
            continue
        text_value = normalize_rp_text(str(item.get("text") or item.get("quote") or ""), limit=300)
        if not text_value or len(text_value) < 5 or confidence < 0.70:
            continue
        if per_episode_counts[episode_no] >= 2:
            continue
        if text_value not in str(episode_texts_by_no.get(episode_no) or ""):
            continue
        key = (episode_no, text_value)
        if key in seen:
            continue
        seen.add(key)
        per_episode_counts[episode_no] += 1
        valid_items.append(
            {
                "kind": "dialogue",
                "context": normalize_rp_text(str(item.get("context") or item.get("evidence") or ""), limit=20),
                "text": text_value,
                "episode_no": episode_no,
            }
        )
    return valid_items


async def collect_llm_rp_dialogue_items(
    summary_client: AsyncClient,
    *,
    target: dict[str, object],
    episode_texts_by_no: dict[int, str],
    aliases: list[str],
) -> list[dict[str, object]]:
    fallback_input = build_rp_dialogue_fallback_input(target, episode_texts_by_no, aliases)
    if not fallback_input:
        return []
    raw_items = await request_rp_dialogue_items(
        summary_client,
        target=target,
        normalized_text=fallback_input,
    )
    return validate_llm_rp_dialogue_items(raw_items, episode_texts_by_no)


def select_rp_example_texts(
    payload: dict,
    dialogue_items: list[dict[str, object]],
    aliases: list[str],
    limit: int = 5,
) -> list[str]:
    dialogue_texts = {
        str(item.get("text") or "").strip()
        for item in dialogue_items
        if str(item.get("kind") or "dialogue").strip().lower() == "dialogue"
        and str(item.get("text") or "").strip()
    }
    selected: list[str] = []
    seen: set[str] = set()
    for item in payload.get("example_dialogues") or []:
        text_value = str(item).strip()
        if (
            text_value
            and text_value in dialogue_texts
            and text_value not in seen
            and is_preferred_rp_example_text(text_value, aliases)
        ):
            selected.append(text_value)
            seen.add(text_value)
        if len(selected) >= limit:
            return selected

    fallback_candidates = sorted(
        [
            item for item in dialogue_items
            if str(item.get("kind") or "dialogue").strip().lower() == "dialogue"
            and bool(item.get("is_example_candidate"))
            and str(item.get("text") or "").strip()
        ],
        key=lambda item: (
            -int(item.get("example_score") or 0),
            int(item.get("episode_no") or 0),
        ),
    )
    for item in fallback_candidates:
        text_value = str(item.get("text") or "").strip()
        if text_value and text_value not in seen:
            selected.append(text_value)
            seen.add(text_value)
        if len(selected) >= limit:
            break
    return selected


def collect_rp_summary_context_lines(
    target: dict[str, object],
    episode_rows: list[dict[str, object]],
    limit: int = 8,
) -> list[str]:
    aliases = [str(alias).strip() for alias in (target.get("aliases") or []) if str(alias).strip()]
    is_protagonist = bool(target.get("is_protagonist"))
    lines: list[str] = []
    seen: set[str] = set()
    for row in episode_rows:
        summary_text = str(row.get("summary_text") or "").strip()
        if not summary_text:
            continue
        if not is_protagonist and aliases and not any(alias in summary_text for alias in aliases):
            continue
        summary_lines = [line.strip() for line in summary_text.splitlines() if line.strip()]
        if not summary_lines:
            continue
        episode_no = int(row.get("episode_from") or 0)
        snippet_parts = summary_lines[:3]
        snippet = normalize_rp_text(" ".join(snippet_parts), limit=240)
        if not snippet or snippet in seen:
            continue
        seen.add(snippet)
        lines.append(f"[{episode_no}화] {snippet}")
        if len(lines) >= limit:
            break
    return lines


async def request_rp_dialogue_items(
    client: AsyncClient,
    *,
    target: dict[str, object],
    normalized_text: str,
) -> list[dict[str, object]]:
    response = await client.post(
        f"{OPENROUTER_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "X-Title": "LikeNovel Story Agent RP Dialogue Batch",
        },
        json=build_rp_openrouter_payload(
            system_prompt=RP_DIALOGUE_COLLECTION_PROMPT,
            user_prompt=build_rp_dialogue_collection_user_prompt(target, normalized_text),
            max_tokens=1800,
        ),
    )
    response.raise_for_status()
    parsed = extract_json_object(extract_openrouter_message_text(response.json())) or {}
    items = parsed.get("items") or []
    cleaned: list[dict[str, object]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text_value = str(item.get("text") or "").strip()
        if not text_value:
            continue
        try:
            episode_no = int(item.get("episode_no") or 0)
            confidence = float(item.get("confidence") or 0.0)
        except (TypeError, ValueError):
            episode_no = 0
            confidence = 0.0
        cleaned.append(
            {
                "kind": str(item.get("kind") or "dialogue").strip().lower() or "dialogue",
                "context": str(item.get("context") or "").strip()[:20],
                "text": text_value[:300],
                "episode_no": episode_no,
                "confidence": confidence,
            }
        )
    return cleaned


async def request_rp_character_plan_payload(
    client: AsyncClient,
    *,
    episode_rows: list[dict[str, object]],
    episode_texts_by_no: dict[int, str],
) -> dict | None:
    user_prompt = build_rp_character_plan_user_prompt(episode_rows, episode_texts_by_no)
    return await request_rp_openrouter_json_payload(
        client,
        system_prompt=RP_CHARACTER_PLAN_PROMPT,
        user_prompt=user_prompt,
        max_tokens=1800,
        title="LikeNovel Story Agent RP Character Plan Batch",
    )


async def request_episode_character_signals_payload(
    client: AsyncClient,
    *,
    row: dict[str, object],
    summary_text: str,
) -> dict | None:
    user_prompt = build_episode_character_signals_user_prompt(row, summary_text)
    episode_no = int(row.get("episode_no") or 0)

    response_payload: dict | None = None
    request_id = ""
    if settings.ANTHROPIC_API_KEY and RP_REASONING_MODEL:
        request_headers = {
            "x-api-key": settings.ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        request_payload = {
            "model": RP_REASONING_MODEL,
            "max_tokens": EPISODE_CHARACTER_SIGNALS_MAX_OUTPUT_TOKENS,
            "system": EPISODE_CHARACTER_SIGNALS_PROMPT,
            "messages": [{"role": "user", "content": user_prompt}],
            "tools": [EPISODE_CHARACTER_SIGNALS_TOOL_SCHEMA],
            "tool_choice": {"type": "tool", "name": EPISODE_CHARACTER_SIGNALS_TOOL_NAME},
            **build_anthropic_reasoning_options(RP_REASONING_MODEL),
        }

        try:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers=request_headers,
                json=request_payload,
            )
            response.raise_for_status()
            response_payload = response.json()
            request_id = (
                response.headers.get("request-id")
                or response.headers.get("x-request-id")
                or response.headers.get("anthropic-request-id")
                or ""
            ).strip()
        except (HTTPStatusError, RequestError) as exc:
            try:
                response = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers=request_headers,
                    json={
                        "model": RP_REASONING_MODEL,
                        "max_tokens": EPISODE_CHARACTER_SIGNALS_MAX_OUTPUT_TOKENS,
                        "system": EPISODE_CHARACTER_SIGNALS_PROMPT,
                        "messages": [{"role": "user", "content": user_prompt}],
                        **build_anthropic_reasoning_options(RP_REASONING_MODEL),
                    },
                )
                response.raise_for_status()
                response_payload = response.json()
                request_id = (
                    response.headers.get("request-id")
                    or response.headers.get("x-request-id")
                    or response.headers.get("anthropic-request-id")
                    or ""
                ).strip()
            except (HTTPStatusError, RequestError) as retry_exc:
                logger.warning(
                    "[storyctx] episode_character_signals anthropic failed episode_no=%s: %s / retry=%s",
                    episode_no,
                    exc,
                    retry_exc,
                )

    tool_payload = extract_anthropic_tool_input(response_payload or {}, tool_name=EPISODE_CHARACTER_SIGNALS_TOOL_NAME)
    if tool_payload:
        return tool_payload

    raw_text = extract_anthropic_message_text(response_payload or {})
    parsed_json = extract_json_object(raw_text)
    if parsed_json:
        return parsed_json

    parsed_text = parse_episode_character_signals_structured_text(raw_text)
    if parsed_text:
        return parsed_text

    if OPENROUTER_API_KEY and EPISODE_CHARACTER_SIGNALS_OPENROUTER_MODEL:
        for attempt in range(2):
            try:
                response = await asyncio.wait_for(
                    client.post(
                        f"{OPENROUTER_BASE_URL}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                            "Content-Type": "application/json",
                            "X-Title": "LikeNovel Story Agent Episode Character Signals OpenRouter",
                        },
                        json=build_character_signals_openrouter_payload(
                            user_prompt=(
                                build_episode_character_signals_user_prompt(row, summary_text)
                                + "\n\nJSON object must satisfy the episode_character_signals schema exactly."
                            ),
                        ),
                    ),
                    timeout=EPISODE_CHARACTER_SIGNALS_OPENROUTER_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                openrouter_payload = extract_json_object(extract_openrouter_message_text(response.json()))
                if openrouter_payload:
                    logger.info(
                        "[storyctx] episode_character_signals provider=openrouter model=%s episode_no=%s",
                        EPISODE_CHARACTER_SIGNALS_OPENROUTER_MODEL,
                        episode_no,
                    )
                    return openrouter_payload
            except (asyncio.TimeoutError, HTTPStatusError, RequestError, ValueError, json.JSONDecodeError) as exc:
                logger.warning(
                    "[storyctx] episode_character_signals openrouter fallback failed episode_no=%s attempt=%s: %s",
                    episode_no,
                    attempt + 1,
                    exc,
                )
                retry_delay = get_openrouter_retry_delay_seconds(exc)
                if attempt == 0 and retry_delay is not None:
                    await asyncio.sleep(retry_delay)

    diagnostics = build_episode_character_signals_parse_diagnostics(raw_text)
    raise EpisodeCharacterSignalsParseError(
        episode_no=episode_no,
        model=RP_REASONING_MODEL or EPISODE_CHARACTER_SIGNALS_OPENROUTER_MODEL,
        request_id=request_id,
        json_parse_ok=bool(diagnostics["json_parse_ok"]),
        line_parse_ok=bool(diagnostics["line_parse_ok"]),
        char_count=int(diagnostics["char_count"]),
        rel_count=int(diagnostics["rel_count"]),
        hook_count=int(diagnostics["hook_count"]),
        raw_sha256=str(diagnostics["raw_sha256"]),
        raw_preview=str(diagnostics["raw_preview"]),
    )


async def request_rp_profile_payload(
    client: AsyncClient,
    *,
    target: dict[str, object],
    dialogue_items: list[dict[str, object]],
    summary_context_lines: list[str],
    inventory_item: dict[str, object] | None = None,
    relation_context_lines: list[str] | None = None,
) -> dict | None:
    user_prompt = build_rp_profile_synthesis_user_prompt(
        target,
        dialogue_items,
        summary_context_lines,
        inventory_item,
        relation_context_lines,
    )
    return await request_rp_openrouter_json_payload(
        client,
        system_prompt=RP_PROFILE_SYNTHESIS_PROMPT,
        user_prompt=user_prompt,
        max_tokens=1200,
        title="LikeNovel Story Agent RP Profile Batch",
    )


def normalize_character_chat_internal_prompt_payload(payload: dict | None) -> dict[str, str] | None:
    if not isinstance(payload, dict):
        return None
    internal_prompt = str(payload.get("internal_prompt") or "").strip()
    if not internal_prompt:
        return None
    return {"internal_prompt": internal_prompt[:4000]}


async def request_character_chat_internal_prompt_payload(
    client: AsyncClient,
    *,
    target: dict[str, object],
    profile_payload: dict[str, object],
    example_payload: dict[str, object],
    dialogue_items: list[dict[str, object]],
    summary_context_lines: list[str],
    inventory_item: dict[str, object] | None = None,
    relation_context_lines: list[str] | None = None,
    scene_context_lines: list[str] | None = None,
) -> dict[str, str] | None:
    payload = await request_rp_openrouter_json_payload(
        client,
        system_prompt=CHARACTER_CHAT_INTERNAL_PROMPT_SYSTEM,
        user_prompt=build_character_chat_internal_prompt_user_prompt(
            target=target,
            profile_payload=profile_payload,
            example_payload=example_payload,
            dialogue_items=dialogue_items,
            summary_context_lines=summary_context_lines,
            inventory_item=inventory_item,
            relation_context_lines=relation_context_lines,
            scene_context_lines=scene_context_lines,
        ),
        max_tokens=3200,
        title="LikeNovel Story Agent Character Chat Internal Prompt Batch",
        timeout_seconds=CHARACTER_CHAT_INTERNAL_PROMPT_TIMEOUT_SECONDS,
    )
    return normalize_character_chat_internal_prompt_payload(payload)


def build_character_chat_opening_user_prompt(
    *,
    scope_key: str,
    target: dict[str, object],
    profile_payload: dict[str, object],
    example_payload: dict[str, object],
    internal_prompt_payload: dict[str, object],
    summary_context_lines: list[str],
    inventory_item: dict[str, object] | None = None,
    relation_context_lines: list[str] | None = None,
    scene_context_lines: list[str] | None = None,
) -> str:
    compact_inventory = {
        key: inventory_item.get(key)
        for key in [
            "display_name",
            "aliases",
            "is_protagonist",
            "is_first_person",
            "work_role",
            "identity_surface",
            "reveal_boundary",
            "read_range_state_snapshot",
            "interaction_affordance_v1",
            "adjacent_event_seed_v1",
            "chat_readiness_v1",
            "public_chat_eligible",
            "public_slot_eligible",
        ]
        if inventory_item and inventory_item.get(key) not in (None, "", [])
    }
    return (
        "[필수 scope_key]\n"
        + scope_key
        + "\n\n[대상 캐릭터]\n"
        + json.dumps(
            {
                "display_name": str(target.get("display_name") or "").strip(),
                "aliases": [str(alias).strip() for alias in (target.get("aliases") or []) if str(alias).strip()],
                "is_protagonist": bool(target.get("is_protagonist")),
                "is_first_person": bool(target.get("is_first_person")),
            },
            ensure_ascii=False,
        )
        + "\n\n[인벤토리]\n"
        + json.dumps(compact_inventory, ensure_ascii=False)
        + "\n\n[RP 프로필]\n"
        + json.dumps(profile_payload, ensure_ascii=False)
        + "\n\n[대표 대사]\n"
        + json.dumps(example_payload, ensure_ascii=False)
        + "\n\n[내부 프롬프트]\n"
        + json.dumps(internal_prompt_payload, ensure_ascii=False)
        + "\n\n[회차 요약 근거]\n"
        + ("\n".join(f"- {line}" for line in summary_context_lines[:8]) if summary_context_lines else "없음")
        + "\n\n[관계 근거]\n"
        + ("\n".join(str(line).strip() for line in (relation_context_lines or [])[:8] if str(line).strip()) or "없음")
        + "\n\n[장면 프레임 근거]\n"
        + ("\n".join(str(line).strip() for line in (scene_context_lines or [])[:8] if str(line).strip()) or "없음")
        + "\n\n위 근거만 사용해 character_chat_opening_v1 JSON을 작성하라."
    )


def normalize_character_chat_opening_payload(
    payload: dict | None,
    *,
    scope_key: str,
    display_name: str,
) -> dict[str, object] | None:
    if not isinstance(payload, dict):
        return None
    readiness = dict(payload.get("readiness") or {})
    if str(readiness.get("status") or "").strip() != "ready":
        return None
    chat_target = dict(payload.get("chat_target") or {})
    payload_scope_key = str(chat_target.get("scope_key") or "").strip()
    if payload_scope_key and payload_scope_key != scope_key:
        return None
    chat_target["scope_key"] = scope_key
    chat_target["display_name"] = str(chat_target.get("display_name") or "").strip() or display_name
    if not chat_target["display_name"]:
        return None
    required_dict_fields = [
        "opening_message",
        "opening_scene",
        "user_role",
        "character_drive",
        "agency_contract",
        "progression_engine",
        "runtime_formula_seed",
    ]
    if any(not isinstance(payload.get(field_name), dict) or not payload.get(field_name) for field_name in required_dict_fields):
        return None
    opening_message = normalize_character_chat_opening_message(payload.get("opening_message"))
    if opening_message is None:
        return None
    runtime_formula_seed = normalize_character_chat_runtime_formula_seed(
        payload.get("runtime_formula_seed")
    )
    if runtime_formula_seed is None:
        return None
    normalized = dict(payload)
    normalized["schema_version"] = CHARACTER_CHAT_OPENING_FORMAT_VERSION
    normalized["readiness"] = readiness
    normalized["chat_target"] = chat_target
    normalized["opening_message"] = opening_message
    normalized["runtime_formula_seed"] = runtime_formula_seed
    return normalized


def normalize_character_chat_runtime_formula_seed(value: object) -> dict[str, str] | None:
    if not isinstance(value, dict) or not value:
        return None
    normalized: dict[str, str] = {}
    for field_name in CHARACTER_CHAT_RUNTIME_FORMULA_REQUIRED_FIELDS:
        field_value = normalize_rp_text(str(value.get(field_name) or ""), limit=700)
        if not field_value:
            return None
        normalized[field_name] = field_value
    return normalized


def normalize_character_chat_opening_message(value: object) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    narration = normalize_rp_text(str(value.get("narration") or ""), limit=900)
    dialogue = normalize_rp_text(str(value.get("dialogue") or ""), limit=600)
    if dialogue and not any(mark in dialogue for mark in ('"', "“", "”")):
        dialogue = f'"{dialogue.strip(chr(34)).strip("“”")}"'
    opening_text = normalize_character_chat_opening_block(str(value.get("opening_text") or ""), limit=1800)
    user_objective = normalize_rp_text(str(value.get("user_objective") or ""), limit=220)
    if not opening_text and narration and dialogue:
        opening_text = f"{narration}\n\n{dialogue}"
    elif opening_text and "\n" not in opening_text and narration and dialogue:
        opening_text = f"{narration}\n\n{dialogue}"
    if not narration or not dialogue or not opening_text or not user_objective:
        return None
    if len(narration) < 220 or len(dialogue) < 20 or len(opening_text) < 280:
        return None
    if dialogue not in opening_text and dialogue.strip('"“”') not in opening_text:
        return None
    if dialogue.strip().lstrip('"“').startswith("거기"):
        return None
    if has_character_chat_opening_agency_violation(f"{dialogue}\n{opening_text}"):
        return None
    return {
        "narration": narration,
        "dialogue": dialogue,
        "opening_text": opening_text,
        "user_objective": user_objective,
    }


def has_character_chat_opening_agency_violation(text: str) -> bool:
    normalized = normalize_rp_text(str(text or ""), limit=2200)
    if not normalized:
        return False
    forbidden_fragments = [
        "멍하니 서",
        "멍하니 있",
        "숨어서",
        "숨어 있",
        "눈치만 보",
        "튀어나와",
        "어슬렁",
        "허가받지 않은",
        "침입자",
        "침입했",
        "목적이 뭐",
        "정체가 뭐",
        "누구냐",
        "왜 여기",
        "대답해",
        "네가 가리킨",
        "네가 들고",
        "네가 내민",
        "네 손",
        "네 발치",
        "너를 향해",
        "너에게",
        "너를 쏘아보",
        "너를 힐끗",
        "너를 쳐다",
    ]
    return any(fragment in normalized for fragment in forbidden_fragments)


def normalize_character_chat_opening_block(value: str, *, limit: int) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").replace("\u3000", " ")
    text = re.sub(r"[ \t]+", " ", text)
    lines: list[str] = []
    blank_seen = False
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            if lines and not blank_seen:
                lines.append("")
            blank_seen = True
            continue
        lines.append(line)
        blank_seen = False
    normalized = "\n".join(lines).strip()
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    if len(normalized) > limit:
        normalized = normalized[:limit].rstrip()
    return normalized


async def request_character_chat_opening_payload(
    client: AsyncClient,
    *,
    scope_key: str,
    target: dict[str, object],
    profile_payload: dict[str, object],
    example_payload: dict[str, object],
    internal_prompt_payload: dict[str, object],
    summary_context_lines: list[str],
    inventory_item: dict[str, object] | None = None,
    relation_context_lines: list[str] | None = None,
    scene_context_lines: list[str] | None = None,
) -> dict[str, object] | None:
    display_name = str(target.get("display_name") or "").strip()
    payload = await request_rp_openrouter_json_payload(
        client,
        system_prompt=CHARACTER_CHAT_OPENING_SYSTEM,
        user_prompt=build_character_chat_opening_user_prompt(
            scope_key=scope_key,
            target=target,
            profile_payload=profile_payload,
            example_payload=example_payload,
            internal_prompt_payload=internal_prompt_payload,
            summary_context_lines=summary_context_lines,
            inventory_item=inventory_item,
            relation_context_lines=relation_context_lines,
            scene_context_lines=scene_context_lines,
        ),
        max_tokens=3000,
        title="LikeNovel Story Agent Character Chat Opening Batch",
    )
    return normalize_character_chat_opening_payload(
        payload,
        scope_key=scope_key,
        display_name=display_name,
    )


async def request_episode_scene_extraction_payload(
    client: AsyncClient,
    *,
    product_title: str,
    episode_no: int,
    episode_title: str,
    normalized_text: str,
    canonical_character_packet: object | None = None,
) -> dict[str, object]:
    user_prompt = build_episode_scene_extraction_user_prompt(
        product_title=product_title,
        episode_no=episode_no,
        episode_title=episode_title,
        normalized_text=normalized_text,
        canonical_character_packet=canonical_character_packet,
    )
    normalized_payload: dict[str, object] = {}
    for attempt in range(2):
        retry_suffix = (
            "\n\n이전 응답은 완전한 JSON object가 아니었다. "
            "이번에는 반드시 닫힌 JSON object 하나만 끝까지 반환하라."
            if attempt
            else ""
        )
        try:
            payload = await request_episode_scene_extraction_openrouter_json_payload(
                client,
                user_prompt=user_prompt + retry_suffix,
            )
        except (asyncio.TimeoutError, HTTPStatusError, RequestError, json.JSONDecodeError) as exc:
            logger.warning(
                "[storyctx] episode_scene_extraction openrouter failed episode_no=%s attempt=%s: %s",
                episode_no,
                attempt + 1,
                exc,
            )
            retry_delay = get_openrouter_retry_delay_seconds(exc)
            if attempt == 0 and retry_delay is not None:
                await asyncio.sleep(retry_delay)
            continue
        normalized_payload = normalize_episode_scene_extraction_payload(
            payload,
            normalized_text=normalized_text,
            canonical_character_packet=canonical_character_packet,
            episode_no=episode_no,
        )
        if _is_usable_episode_scene_payload(normalized_payload):
            return normalized_payload
    return normalized_payload


def build_rp_inventory_signature_parts(inventory_item: dict[str, object] | None) -> list[str]:
    if not inventory_item:
        return []
    return [
        f"inv:first:{int(inventory_item.get('first_seen_episode_no') or 0)}",
        f"inv:episodes:{int(inventory_item.get('distinct_episode_count') or 0)}",
        f"inv:mentions:{int(inventory_item.get('summary_mention_count') or 0)}",
        f"inv:voice:{int(inventory_item.get('voice_evidence_count') or 0)}",
        f"inv:action:{str(inventory_item.get('action_presence') or '')}",
        f"inv:relation:{str(inventory_item.get('relation_presence') or '')}",
    ]


def build_character_chat_inventory_signature_parts(inventory_item: dict[str, object] | None) -> list[str]:
    if not inventory_item:
        return []
    return [
        *build_rp_inventory_signature_parts(inventory_item),
        "inv:identity_surface:"
        + json.dumps(dict(inventory_item.get("identity_surface") or {}), ensure_ascii=False, sort_keys=True),
        "inv:reveal_boundary:"
        + json.dumps(dict(inventory_item.get("reveal_boundary") or {}), ensure_ascii=False, sort_keys=True),
        "inv:read_range_state:"
        + json.dumps(dict(inventory_item.get("read_range_state_snapshot") or {}), ensure_ascii=False, sort_keys=True),
        "inv:interaction_affordance:"
        + json.dumps(dict(inventory_item.get("interaction_affordance_v1") or {}), ensure_ascii=False, sort_keys=True),
        "inv:adjacent_event_seed:"
        + json.dumps(dict(inventory_item.get("adjacent_event_seed_v1") or {}), ensure_ascii=False, sort_keys=True),
        "inv:pov_centrality:"
        + json.dumps(dict(inventory_item.get("pov_and_protagonist_centrality_v1") or {}), ensure_ascii=False, sort_keys=True),
        "inv:voice_contract:"
        + json.dumps(dict(inventory_item.get("voice_contract_v1") or {}), ensure_ascii=False, sort_keys=True),
        "inv:chat_readiness:"
        + json.dumps(dict(inventory_item.get("chat_readiness_v1") or {}), ensure_ascii=False, sort_keys=True),
    ]


def build_rp_profile_source_hash(
    *,
    character_key: str,
    inventory_item: dict[str, object] | None,
    dialogue_items: list[dict[str, object]],
    summary_context_lines: list[str],
    relation_context_lines: list[str],
) -> str:
    return build_compound_summary_source_hash(
        CHARACTER_RP_PROFILE_FORMAT_VERSION,
        [
            character_key,
            build_rp_profile_model_signature(),
            *build_rp_inventory_signature_parts(inventory_item),
            *(f"summary:{line}" for line in summary_context_lines[:8]),
            *(f"relation:{line}" for line in relation_context_lines[:6]),
            *(f"{int(item.get('episode_no') or 0)}:{str(item.get('text') or '')}" for item in dialogue_items[:40]),
        ],
    )


def build_rp_examples_source_hash(
    *,
    character_key: str,
    inventory_item: dict[str, object] | None,
    example_payload: dict[str, object],
    summary_context_lines: list[str],
    relation_context_lines: list[str],
) -> str:
    return build_compound_summary_source_hash(
        CHARACTER_RP_EXAMPLES_FORMAT_VERSION,
        [
            character_key,
            build_rp_profile_model_signature(),
            *build_rp_inventory_signature_parts(inventory_item),
            *(f"summary:{line}" for line in summary_context_lines[:8]),
            *(f"relation:{line}" for line in relation_context_lines[:6]),
            *(
                "example:"
                + json.dumps(
                    dict(item),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                for item in list(example_payload.get("examples") or [])
                if isinstance(item, dict)
            ),
        ],
    )


def build_character_chat_internal_prompt_source_hash(
    *,
    character_key: str,
    inventory_item: dict[str, object] | None,
    profile_payload: dict[str, object],
    example_payload: dict[str, object],
    dialogue_items: list[dict[str, object]],
    summary_context_lines: list[str],
    relation_context_lines: list[str],
    scene_context_lines: list[str] | None = None,
) -> str:
    return build_compound_summary_source_hash(
        CHARACTER_CHAT_INTERNAL_PROMPT_FORMAT_VERSION,
        [
            character_key,
            build_rp_profile_model_signature(),
            *build_character_chat_inventory_signature_parts(inventory_item),
            json.dumps(profile_payload, ensure_ascii=False, sort_keys=True),
            *(str(item.get("text") or "") for item in list(example_payload.get("examples") or [])),
            *(f"summary:{line}" for line in summary_context_lines[:8]),
            *(f"relation:{line}" for line in relation_context_lines[:8]),
            *(f"scene:{line}" for line in list(scene_context_lines or [])[:8]),
            *(f"{int(item.get('episode_no') or 0)}:{str(item.get('text') or '')}" for item in dialogue_items[:40]),
        ],
    )


def build_character_chat_opening_source_hash(
    *,
    character_key: str,
    inventory_item: dict[str, object] | None,
    profile_row: dict[str, object],
    examples_row: dict[str, object],
    internal_prompt_row: dict[str, object],
    summary_context_lines: list[str],
    relation_context_lines: list[str],
    scene_context_lines: list[str] | None = None,
) -> str:
    return build_compound_summary_source_hash(
        CHARACTER_CHAT_OPENING_FORMAT_VERSION,
        [
            CHARACTER_CHAT_OPENING_RUNTIME_FORMULA_CONTRACT_VERSION,
            character_key,
            build_rp_profile_model_signature(),
            *build_character_chat_inventory_signature_parts(inventory_item),
            f"profile:{str(profile_row.get('source_hash') or '')}",
            f"examples:{str(examples_row.get('source_hash') or '')}",
            f"internal:{str(internal_prompt_row.get('source_hash') or '')}",
            *(f"summary:{line}" for line in summary_context_lines[:8]),
            *(f"relation:{line}" for line in relation_context_lines[:8]),
            *(f"scene:{line}" for line in list(scene_context_lines or [])[:8]),
        ],
    )


def build_inventory_rp_target(
    *,
    scope_key: str,
    inventory_item: dict[str, object],
) -> dict[str, object] | None:
    display_name = str(inventory_item.get("display_name") or "").strip()
    if not display_name:
        return None
    is_protagonist = bool(inventory_item.get("is_protagonist"))
    is_first_person = bool(inventory_item.get("is_first_person")) if is_protagonist else False
    aliases: list[str] = []
    for alias in [display_name, *list(inventory_item.get("aliases") or [])]:
        alias_text = str(alias).strip()
        if alias_text and alias_text not in aliases:
            aliases.append(alias_text)
    if is_protagonist and "주인공" not in aliases:
        aliases.append("주인공")
    evidence_episode_nos = [
        int(value)
        for value in list(inventory_item.get("evidence_episode_nos") or [])
        if int(value) > 0
    ]
    return {
        "character_key": scope_key,
        "display_name": display_name,
        "reference_name": display_name,
        "is_protagonist": is_protagonist,
        "is_first_person": is_first_person,
        "aliases": aliases[:6],
        "display_safety": dict(inventory_item.get("display_safety") or {}),
        "public_chat_eligible": inventory_item.get("public_chat_eligible"),
        "public_slot_eligible": inventory_item.get("public_slot_eligible"),
        "evidence_episodes": sorted(set(evidence_episode_nos))[:6],
        "collection_rules": {
            "use_dialogue": True,
            "use_monologue": bool(is_protagonist and is_first_person),
            "speaker_anchors": aliases[:6],
            "exclude_tokens": [],
            "priority_patterns": [],
        },
    }


def collect_inventory_speaker_anchors(inventory_item: dict[str, object]) -> list[str]:
    anchors: list[str] = []
    for alias in [inventory_item.get("display_name"), *list(inventory_item.get("aliases") or [])]:
        alias_text = str(alias or "").strip()
        if not alias_text:
            continue
        if normalize_signal_entity_label(alias_text) in GENERIC_CHARACTER_LABELS and not _has_strong_role_like_persona_evidence(inventory_item):
            continue
        if alias_text not in anchors:
            anchors.append(alias_text)
    return anchors


def attach_competing_speaker_anchors(
    target: dict[str, object],
    *,
    current_scope_key: str,
    inventory_map: dict[str, dict[str, object]],
) -> dict[str, object]:
    copied = dict(target)
    rules = dict(copied.get("collection_rules") or {})
    target_anchors = {
        str(anchor).strip()
        for anchor in [copied.get("display_name"), *list(copied.get("aliases") or []), *list(rules.get("speaker_anchors") or [])]
        if str(anchor).strip()
    }
    competing: list[str] = []
    for scope_key, inventory_item in (inventory_map or {}).items():
        if str(scope_key) == str(current_scope_key):
            continue
        for anchor in collect_inventory_speaker_anchors(dict(inventory_item or {})):
            if anchor in target_anchors or anchor in competing:
                continue
            competing.append(anchor)
    rules["competing_speaker_anchors"] = competing[:120]
    copied["collection_rules"] = rules
    return copied


def build_inventory_rp_targets(
    inventory_map: dict[str, dict[str, object]],
    *,
    limit: int = RP_PROFILE_MAX_TARGETS_PER_PRODUCT,
) -> list[dict[str, object]]:
    candidates: list[tuple[tuple[object, ...], dict[str, object]]] = []
    for scope_key, inventory_item in (inventory_map or {}).items():
        inventory_payload = dict(inventory_item or {})
        if not is_batch_rp_candidate(inventory_payload):
            continue
        target = build_inventory_rp_target(scope_key=str(scope_key), inventory_item=inventory_payload)
        if not target or get_rp_target_skip_reason(target):
            continue
        target = attach_competing_speaker_anchors(
            target,
            current_scope_key=str(scope_key),
            inventory_map=inventory_map,
        )
        candidates.append(
            (
                (
                    0 if bool(inventory_payload.get("is_protagonist")) else 1,
                    -int(inventory_payload.get("distinct_episode_count") or 0),
                    -int(inventory_payload.get("voice_evidence_count") or 0),
                    str(inventory_payload.get("display_name") or ""),
                ),
                target,
            )
        )
    return [target for _, target in sorted(candidates, key=lambda item: item[0])[:limit]]


def build_inventory_rp_retained_scope_keys(
    inventory_map: dict[str, dict[str, object]],
) -> set[str]:
    retained_scope_keys: set[str] = set()
    for scope_key, inventory_item in (inventory_map or {}).items():
        inventory_payload = dict(inventory_item or {})
        if not is_batch_rp_candidate(inventory_payload):
            continue
        target = build_inventory_rp_target(
            scope_key=str(scope_key), inventory_item=inventory_payload
        )
        if not target or get_rp_target_skip_reason(target):
            continue
        retained_scope_keys.update(
            build_inventory_scope_alias_keys(str(scope_key), inventory_payload)
        )
    return retained_scope_keys


def build_inventory_scope_alias_key_candidates(scope_key: str, inventory_item: dict[str, object] | None) -> list[str]:
    alias_keys: list[str] = []

    def append_key(value: object) -> None:
        alias_key = str(value or "").strip()
        if alias_key and alias_key not in alias_keys:
            alias_keys.append(alias_key)

    append_key(scope_key)
    payload = dict(inventory_item or {})
    for field_name in ("character_key", "canonical_character_key"):
        append_key(payload.get(field_name))
    for source_key in list(payload.get("source_character_keys") or []):
        append_key(source_key)
    return alias_keys


def build_inventory_scope_alias_keys(scope_key: str, inventory_item: dict[str, object] | None) -> set[str]:
    return set(build_inventory_scope_alias_key_candidates(scope_key, inventory_item))


def fetch_summary_state_for_inventory_alias(
    rows_by_scope: dict[str, dict[str, object]],
    *,
    scope_key: str,
    inventory_item: dict[str, object] | None,
    allowed_alias_keys: set[str] | None = None,
) -> dict[str, object]:
    for alias_key in build_inventory_scope_alias_key_candidates(scope_key, inventory_item):
        if alias_key != scope_key and allowed_alias_keys is not None and alias_key not in allowed_alias_keys:
            continue
        row = rows_by_scope.get(alias_key)
        if row:
            return dict(row)
    return {}


def fetch_legacy_summary_state_for_inventory_alias(
    rows_by_scope: dict[str, dict[str, object]],
    *,
    scope_key: str,
    inventory_item: dict[str, object] | None,
    allowed_alias_keys: set[str] | None = None,
) -> dict[str, object]:
    for alias_key in build_inventory_scope_alias_key_candidates(scope_key, inventory_item):
        if alias_key == scope_key:
            continue
        if allowed_alias_keys is not None and alias_key not in allowed_alias_keys:
            continue
        row = rows_by_scope.get(alias_key)
        if row:
            return dict(row)
    return {}


def canonicalize_character_chat_payload_scope(
    payload: dict[str, object],
    *,
    scope_key: str,
    display_name: str,
) -> dict[str, object]:
    copied = dict(payload or {})
    copied["character_key"] = scope_key
    if display_name and not str(copied.get("display_name") or "").strip():
        copied["display_name"] = display_name
    return copied


def build_rp_dialogue_items_from_example_payload(example_payload: dict[str, object]) -> list[dict[str, object]]:
    dialogue_items: list[dict[str, object]] = []
    for item in list(example_payload.get("examples") or []):
        if not isinstance(item, dict):
            continue
        payload = dict(item or {})
        text = str(payload.get("text") or "").strip()
        if not text:
            continue
        try:
            episode_no = int(payload.get("episode_no") or 0)
        except (TypeError, ValueError):
            episode_no = 0
        try:
            confidence = float(payload.get("confidence") or 0.7)
        except (TypeError, ValueError):
            confidence = 0.7
        dialogue_items.append(
            {
                "episode_no": episode_no,
                "kind": str(payload.get("source_kind") or "dialogue").strip() or "dialogue",
                "text": text,
                "confidence": confidence,
                "is_example_candidate": True,
            }
        )
    return dialogue_items


def select_delta_rp_scope_keys(
    *,
    refresh_requested: bool,
    affected_scope_keys: set[str],
    inventory_map: dict[str, dict[str, object]],
    profile_map: dict[str, dict[str, object]],
    examples_map: dict[str, dict[str, object]],
) -> set[str]:
    if refresh_requested:
        return set(affected_scope_keys)

    missing_scope_keys: set[str] = set()
    for target in build_inventory_rp_targets(inventory_map or {}):
        scope_key = str(target.get("character_key") or "").strip()
        if not scope_key:
            continue
        profile_payload = dict(dict((profile_map or {}).get(scope_key) or {}).get("payload") or {})
        examples_payload = dict(dict((examples_map or {}).get(scope_key) or {}).get("payload") or {})
        if not profile_payload or not build_rp_dialogue_items_from_example_payload(examples_payload):
            missing_scope_keys.add(scope_key)
    return missing_scope_keys


def is_batch_rp_candidate(inventory_item: dict[str, object] | None) -> bool:
    if not inventory_item:
        return False
    if bool(inventory_item.get("is_protagonist")):
        return True
    identity_conflict_reasons = {
        str(reason).strip()
        for field_name in ("identity_conflict_reasons", "review_reasons")
        for reason in list(inventory_item.get(field_name) or [])
        if str(reason).strip()
    }
    if "duplicate_canonical_key" in identity_conflict_reasons:
        return False
    entity_kind = str(inventory_item.get("entity_kind") or "").strip().lower() or "person"
    if entity_kind not in {"person", "stable_role"}:
        return False
    return any(
        int(inventory_item.get(field_name) or 0) > 0
        for field_name in ("voice_evidence_count", "distinct_episode_count", "summary_mention_count")
    )


def extract_relation_character_keys(
    relation_keys: set[str],
    *relation_maps: dict[str, dict[str, object]],
) -> set[str]:
    affected_scope_keys: set[str] = set()
    for relation_map in relation_maps:
        for relation_key in relation_keys:
            payload = dict((relation_map or {}).get(relation_key) or {})
            for field_name in ("source_key", "target_key"):
                scope_key = str(payload.get(field_name) or "").strip()
                if scope_key:
                    affected_scope_keys.add(scope_key)
    return affected_scope_keys


def build_inventory_source_scope_key_map(inventory_map: dict[str, dict[str, object]]) -> dict[str, str]:
    exact_claims: dict[str, set[str]] = {}
    source_claims: dict[str, set[str]] = {}
    for scope_key, inventory_item in (inventory_map or {}).items():
        normalized_scope_key = str(scope_key or "").strip()
        if not normalized_scope_key:
            continue
        exact_claims.setdefault(normalized_scope_key, set()).add(normalized_scope_key)
        payload = dict(inventory_item or {})
        for field_name in ("character_key", "canonical_character_key"):
            source_key = str(payload.get(field_name) or "").strip()
            if source_key:
                exact_claims.setdefault(source_key, set()).add(normalized_scope_key)
        for source_key_value in list(payload.get("source_character_keys") or []):
            source_key = str(source_key_value or "").strip()
            if source_key:
                source_claims.setdefault(source_key, set()).add(normalized_scope_key)
    source_scope_key_map = {
        alias_key: next(iter(owner_scope_keys))
        for alias_key, owner_scope_keys in exact_claims.items()
        if len(owner_scope_keys) == 1
    }
    for alias_key, owner_scope_keys in source_claims.items():
        if alias_key in exact_claims or len(owner_scope_keys) != 1:
            continue
        source_scope_key_map[alias_key] = next(iter(owner_scope_keys))
    return source_scope_key_map


def build_inventory_ambiguous_source_scope_keys(
    inventory_map: dict[str, dict[str, object]],
) -> set[str]:
    source_claims: dict[str, set[str]] = {}
    for scope_key, inventory_item in (inventory_map or {}).items():
        normalized_scope_key = str(scope_key or "").strip()
        if not normalized_scope_key:
            continue
        for source_key_value in list(dict(inventory_item or {}).get("source_character_keys") or []):
            source_key = str(source_key_value or "").strip()
            if source_key:
                source_claims.setdefault(source_key, set()).add(normalized_scope_key)
    return {
        source_key
        for source_key, owner_scope_keys in source_claims.items()
        if len(owner_scope_keys) > 1
    }


def compute_rp_affected_scope_keys(
    *,
    old_inventory_map: dict[str, dict[str, object]],
    new_inventory_map: dict[str, dict[str, object]],
    old_relation_map: dict[str, dict[str, object]],
    new_relation_map: dict[str, dict[str, object]],
    old_touched_signal_rows: list[dict],
    new_touched_signal_rows: list[dict],
    old_profile_map: dict[str, dict[str, object]],
    old_examples_map: dict[str, dict[str, object]],
    old_internal_prompt_map: dict[str, dict[str, object]] | None = None,
    cleanup_scope_keys: set[str] | None = None,
) -> set[str]:
    internal_prompt_gate_enabled = old_internal_prompt_map is not None
    old_internal_prompt_map = old_internal_prompt_map or {}
    touched_character_keys = extract_character_keys_from_signal_rows(old_touched_signal_rows) | extract_character_keys_from_signal_rows(new_touched_signal_rows)
    touched_relation_keys = extract_relation_keys_from_signal_rows(old_touched_signal_rows) | extract_relation_keys_from_signal_rows(new_touched_signal_rows)
    changed_relation_keys = {
        relation_key
        for relation_key in touched_relation_keys
        if dict((old_relation_map or {}).get(relation_key) or {}) != dict((new_relation_map or {}).get(relation_key) or {})
    }
    relation_character_keys = extract_relation_character_keys(changed_relation_keys, old_relation_map, new_relation_map)
    old_source_scope_key_map = build_inventory_source_scope_key_map(old_inventory_map or {})
    new_source_scope_key_map = build_inventory_source_scope_key_map(new_inventory_map or {})
    ambiguous_source_scope_keys = (
        build_inventory_ambiguous_source_scope_keys(old_inventory_map or {})
        | build_inventory_ambiguous_source_scope_keys(new_inventory_map or {})
    )

    def resolve_inventory_scope_keys(raw_scope_keys: set[str]) -> set[str]:
        resolved_scope_keys: set[str] = set()
        for raw_scope_key in raw_scope_keys:
            source_key = str(raw_scope_key or "").strip()
            if not source_key:
                continue
            mapped_scope_keys = {
                str(scope_key or "").strip()
                for scope_key in (
                    old_source_scope_key_map.get(source_key),
                    new_source_scope_key_map.get(source_key),
                )
                if str(scope_key or "").strip()
            }
            if mapped_scope_keys:
                resolved_scope_keys.update(mapped_scope_keys)
            elif source_key not in ambiguous_source_scope_keys:
                resolved_scope_keys.add(source_key)
            if (
                source_key not in ambiguous_source_scope_keys
                and (
                    source_key in old_profile_map
                    or source_key in old_examples_map
                    or source_key in old_internal_prompt_map
                )
            ):
                resolved_scope_keys.add(source_key)
        return resolved_scope_keys

    candidate_scope_keys = resolve_inventory_scope_keys(set(cleanup_scope_keys or set()))
    resolved_relation_scope_keys = resolve_inventory_scope_keys(relation_character_keys)
    for scope_key in resolve_inventory_scope_keys(touched_character_keys | relation_character_keys):
        old_inventory_item = dict((old_inventory_map or {}).get(scope_key) or {})
        new_inventory_item = dict((new_inventory_map or {}).get(scope_key) or {})
        known_scope = bool(
            old_inventory_item
            or new_inventory_item
            or scope_key in old_profile_map
            or scope_key in old_examples_map
            or scope_key in old_internal_prompt_map
        )
        if not known_scope:
            continue
        if (
            old_inventory_item != new_inventory_item
            or scope_key in resolved_relation_scope_keys
            or (new_inventory_item and scope_key not in old_profile_map)
            or (new_inventory_item and scope_key not in old_examples_map)
            or (internal_prompt_gate_enabled and new_inventory_item and scope_key not in old_internal_prompt_map)
            or (
                not old_inventory_item
                and not new_inventory_item
                and (
                    scope_key in old_profile_map
                    or scope_key in old_examples_map
                    or scope_key in old_internal_prompt_map
                )
            )
        ):
            candidate_scope_keys.add(scope_key)
    return {scope_key for scope_key in candidate_scope_keys if str(scope_key or "").strip()}


def build_rp_delta_verification(
    *,
    product_id: int,
    affected_scope_keys: set[str],
    inventory_map: dict[str, dict[str, object]],
    profile_map: dict[str, dict[str, object]],
    examples_map: dict[str, dict[str, object]],
    rp_counts: dict[str, object],
) -> dict[str, object]:
    eligible_scope_keys = sorted(
        scope_key
        for scope_key in affected_scope_keys
        if is_batch_rp_candidate(inventory_map.get(scope_key))
    )
    missing_profile_scope_keys = [scope_key for scope_key in eligible_scope_keys if scope_key not in profile_map]
    missing_examples_scope_keys = [scope_key for scope_key in eligible_scope_keys if scope_key not in examples_map]
    return {
        "product_id": product_id,
        "affected_scope_keys": len(affected_scope_keys),
        "eligible_scope_keys": len(eligible_scope_keys),
        "inserted_profile_count": int((rp_counts.get("profile") or (0, 0))[0]),
        "reused_profile_count": int((rp_counts.get("profile") or (0, 0))[1]),
        "inserted_examples_count": int((rp_counts.get("examples") or (0, 0))[0]),
        "reused_examples_count": int((rp_counts.get("examples") or (0, 0))[1]),
        "deactivated_profile_count": int(rp_counts.get("deactivated_profile_count") or 0),
        "deactivated_examples_count": int(rp_counts.get("deactivated_examples_count") or 0),
        "keep_old_dialogue_missing_count": int(rp_counts.get("keep_old_dialogue_missing_count") or 0),
        "keep_old_examples_missing_count": int(rp_counts.get("keep_old_examples_missing_count") or 0),
        "missing_profile_count_after": len(missing_profile_scope_keys),
        "missing_examples_count_after": len(missing_examples_scope_keys),
        "missing_profile_scope_keys": missing_profile_scope_keys[:10],
        "missing_examples_scope_keys": missing_examples_scope_keys[:10],
    }


def _context_payload_dict(context_payload: dict[str, object], *field_names: str) -> dict[str, object]:
    for field_name in field_names:
        value = context_payload.get(field_name)
        if isinstance(value, dict):
            return dict(value)
    return {}


def _unique_nonempty_texts(values: Iterable[object]) -> list[str]:
    texts: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in texts:
            texts.append(text)
    return texts


def _count_truthy_leaf_values(value: object) -> int:
    if isinstance(value, dict):
        return sum(_count_truthy_leaf_values(item) for item in value.values())
    if isinstance(value, list):
        return sum(_count_truthy_leaf_values(item) for item in value)
    return 1 if str(value or "").strip() else 0


def build_character_chat_context_richness_metrics(context_payload: dict[str, object]) -> dict[str, object]:
    inventory = _context_payload_dict(context_payload, "inventory", "inventory_item", "inventory_payload")
    profile = _context_payload_dict(context_payload, "profile", "profile_payload")
    examples_payload = _context_payload_dict(context_payload, "examples", "examples_payload")
    examples = [item for item in list(examples_payload.get("examples") or []) if isinstance(item, dict)]
    aliases = _unique_nonempty_texts([inventory.get("display_name"), *list(inventory.get("aliases") or [])])
    identity_names = _unique_nonempty_texts(
        [
            *list(inventory.get("narration_names") or []),
            *list(inventory.get("social_call_names") or []),
            *list(inventory.get("persona_names") or []),
            *list(inventory.get("real_names") or []),
        ]
    )
    evidence_episode_nos = {
        int(value)
        for value in list(inventory.get("evidence_episode_nos") or [])
        if int(value or 0) > 0
    }
    example_episode_nos = {
        int(item.get("episode_no") or 0)
        for item in examples
        if int(item.get("episode_no") or 0) > 0
    }
    summary_context_lines = [line for line in list(context_payload.get("summary_context_lines") or []) if str(line or "").strip()]
    relation_context_lines = [line for line in list(context_payload.get("relation_context_lines") or []) if str(line or "").strip()]
    speech_style_field_count = _count_truthy_leaf_values(profile.get("speech_style") or {})
    personality_core_count = len(_unique_nonempty_texts(list(profile.get("personality_core") or [])))
    baseline_attitude_present = 1 if str(profile.get("baseline_attitude") or "").strip() else 0
    example_text_chars = sum(len(str(item.get("text") or "").strip()) for item in examples)
    relation_signal_count = int(inventory.get("relation_episode_count") or 0) + len(relation_context_lines)
    richness_score = (
        len(aliases)
        + len(identity_names) * 2
        + min(len(evidence_episode_nos), 10)
        + relation_signal_count * 2
        + speech_style_field_count * 2
        + personality_core_count * 3
        + baseline_attitude_present * 2
        + len(examples) * 4
        + min(example_text_chars // 40, 10)
        + len(summary_context_lines)
    )
    return {
        "alias_count": len(aliases),
        "identity_name_signal_count": len(identity_names),
        "evidence_episode_count": len(evidence_episode_nos),
        "relation_signal_count": relation_signal_count,
        "speech_style_field_count": speech_style_field_count,
        "personality_core_count": personality_core_count,
        "baseline_attitude_present": baseline_attitude_present,
        "example_count": len(examples),
        "example_episode_count": len(example_episode_nos),
        "example_text_chars": example_text_chars,
        "summary_context_line_count": len(summary_context_lines),
        "richness_score": richness_score,
    }


def compare_character_chat_context_richness(
    baseline_context: dict[str, object],
    candidate_context: dict[str, object],
) -> dict[str, object]:
    baseline_metrics = build_character_chat_context_richness_metrics(baseline_context)
    candidate_metrics = build_character_chat_context_richness_metrics(candidate_context)
    deltas = {
        key: int(candidate_metrics.get(key) or 0) - int(baseline_metrics.get(key) or 0)
        for key in baseline_metrics
        if isinstance(baseline_metrics.get(key), int)
    }
    return {
        "baseline": baseline_metrics,
        "candidate": candidate_metrics,
        "deltas": deltas,
        "improved_metrics": sorted(key for key, value in deltas.items() if value > 0 and key != "richness_score"),
        "regressed_metrics": sorted(key for key, value in deltas.items() if value < 0 and key != "richness_score"),
        "richness_delta": int(deltas.get("richness_score") or 0),
    }


async def build_rp_summaries(
    conn,
    *,
    product_id: int,
    episode_rows: list[dict],
    episode_texts_by_no: dict[int, str],
    summary_client: AsyncClient | None,
    inventory_map: dict[str, dict[str, object]] | None = None,
    relation_map: dict[str, list[dict[str, object]]] | None = None,
    verbose: bool = False,
) -> dict[str, tuple[int, int]]:
    counts = {
        "profile": [0, 0],
        "examples": [0, 0],
    }
    if summary_client is None or not OPENROUTER_API_KEY or not RP_OPENROUTER_MODEL:
        return {key: (value[0], value[1]) for key, value in counts.items()}

    inventory_source_provided = inventory_map is not None
    targets: list[dict[str, object]] = build_inventory_rp_targets(inventory_map or {})
    if not targets and not inventory_source_provided:
        try:
            plan_payload = await request_rp_character_plan_payload(
                summary_client,
                episode_rows=episode_rows,
                episode_texts_by_no=episode_texts_by_no,
            )
            targets = normalize_rp_character_plan(plan_payload, episode_rows, episode_texts_by_no)
        except Exception as exc:
            if verbose:
                print(f"[rp-plan-skip] product_id={product_id} error={str(exc)[:160]}")
    if not targets:
        logger.info("story_agent_rp_keep_old product_id=%s reason=%s", product_id, "plan_targets_missing")
        return {key: (value[0], value[1]) for key, value in counts.items()}

    scene_context_lines_by_scope = load_character_chat_scene_context_lines_by_scope(
        conn,
        product_id=product_id,
    )
    existing_example_rows_by_scope: dict[str, dict[str, object]] | None = None
    source_scope_key_map = build_inventory_source_scope_key_map(inventory_map or {})
    valid_scope_keys = build_inventory_rp_retained_scope_keys(inventory_map or {})
    for target in targets:
        character_key = str(target.get("character_key") or "").strip()
        if not character_key:
            continue
        inventory_item = dict((inventory_map or {}).get(character_key) or {})
        valid_scope_keys.update(build_inventory_scope_alias_keys(character_key, inventory_item))
        skip_reason = get_rp_target_skip_reason(target)
        if skip_reason:
            logger.info(
                "story_agent_rp_keep_old product_id=%s scope_key=%s reason=%s",
                product_id,
                character_key,
                skip_reason,
            )
            continue
        target = attach_competing_speaker_anchors(
            target,
            current_scope_key=character_key,
            inventory_map=inventory_map or {},
        )
        aliases = [str(alias).strip() for alias in (target.get("aliases") or []) if str(alias).strip()]
        direct_voice_quality = build_direct_voice_evidence_quality(target, episode_texts_by_no)
        direct_dialogue_items = collect_rule_based_rp_dialogue_items_by_episode(target, episode_texts_by_no)
        dialogue_items: list[dict[str, object]] = []
        if not bool(direct_voice_quality.get("strict_chat_ready")):
            try:
                llm_dialogue_items = await collect_llm_rp_dialogue_items(
                    summary_client,
                    target=target,
                    episode_texts_by_no=episode_texts_by_no,
                    aliases=aliases,
                )
            except Exception as exc:
                if verbose:
                    print(f"[rp-dialogue-skip] product_id={product_id} character={character_key} error={str(exc)[:160]}")
                llm_dialogue_items = []
            dialogue_items = dedupe_rp_dialogue_items(
                [*direct_dialogue_items, *llm_dialogue_items],
                limit=80,
            )
            dialogue_items = mark_rp_example_candidates(dialogue_items, aliases)
            if sum(bool(item.get("is_example_candidate")) for item in dialogue_items) < RP_PROFILE_MIN_EXAMPLE_TEXTS:
                if existing_example_rows_by_scope is None:
                    with work_cursor(conn) as cur:
                        existing_example_rows_by_scope = fetch_active_summary_state_map(
                            cur=cur,
                            product_id=product_id,
                            summary_type="character_rp_examples",
                        )
                existing_example_row = fetch_summary_state_for_inventory_alias(
                    existing_example_rows_by_scope,
                    scope_key=character_key,
                    inventory_item=inventory_item,
                    allowed_alias_keys={
                        alias_key
                        for alias_key, owner_scope_key in source_scope_key_map.items()
                        if owner_scope_key == character_key
                    },
                )
                dialogue_items = build_rp_dialogue_items_from_example_payload(
                    dict(existing_example_row.get("payload") or {})
                )
                if not dialogue_items:
                    logger.info(
                        "story_agent_rp_keep_old product_id=%s scope_key=%s reason=%s status=%s",
                        product_id,
                        character_key,
                        "direct_voice_not_ready",
                        str(direct_voice_quality.get("status") or "unknown"),
                    )
                    continue
        else:
            dialogue_items = direct_dialogue_items
        if not dialogue_items:
            logger.info(
                "story_agent_rp_keep_old product_id=%s scope_key=%s reason=%s status=%s",
                product_id,
                character_key,
                "dialogue_items_missing",
                str(direct_voice_quality.get("status") or "unknown"),
            )
            continue

        dialogue_items = dedupe_rp_dialogue_items(dialogue_items, limit=80)
        dialogue_items = mark_rp_example_candidates(dialogue_items, aliases)
        summary_context_lines = collect_rp_summary_context_lines(target, episode_rows)
        relation_context_lines = build_rp_relation_context_lines(
            character_key=character_key,
            relation_map=relation_map or {},
        )
        scene_context_lines = scene_context_lines_by_scope.get(character_key, [])

        if not dialogue_items:
            logger.info(
                "story_agent_rp_keep_old product_id=%s scope_key=%s reason=%s",
                product_id,
                character_key,
                "dialogue_items_missing",
            )
            continue

        try:
            payload = await request_rp_profile_payload(
                summary_client,
                target=target,
                dialogue_items=dialogue_items,
                summary_context_lines=summary_context_lines,
                inventory_item=inventory_item,
                relation_context_lines=relation_context_lines,
            )
        except Exception as exc:
            if verbose:
                print(f"[rp-profile-skip] product_id={product_id} character={character_key} error={str(exc)[:160]}")
            continue
        if not payload:
            logger.info(
                "story_agent_rp_keep_old product_id=%s scope_key=%s reason=%s",
                product_id,
                character_key,
                "profile_payload_missing",
            )
            continue

        profile_payload = {
            "character_key": character_key,
            "display_name": str(target.get("display_name") or "").strip() or str(target.get("reference_name") or "").strip(),
            "aliases": [str(alias).strip() for alias in (target.get("aliases") or []) if str(alias).strip()],
            "speech_style": payload.get("speech_style") or {},
            "personality_core": [str(item).strip() for item in (payload.get("personality_core") or []) if str(item).strip()][:2],
            "baseline_attitude": str(payload.get("baseline_attitude") or "").strip() or "무난",
        }
        example_texts = select_rp_example_texts(payload, dialogue_items, aliases)
        if not has_enough_rp_example_texts(example_texts):
            logger.info(
                "story_agent_rp_keep_old product_id=%s scope_key=%s reason=%s selected_examples=%s min_examples=%s",
                product_id,
                character_key,
                "example_texts_below_min",
                len(example_texts),
                RP_PROFILE_MIN_EXAMPLE_TEXTS,
            )
            continue
        example_payload = {
            "character_key": character_key,
            "examples": [],
        }
        for example_text in example_texts:
            matched_item = next((item for item in dialogue_items if str(item.get("text") or "").strip() == example_text), None)
            example_payload["examples"].append(
                {
                    "episode_no": int((matched_item or {}).get("episode_no") or 0),
                    "source_kind": str((matched_item or {}).get("kind") or "dialogue"),
                    "text": example_text,
                    "confidence": 0.9 if matched_item else 0.7,
                }
            )
        internal_prompt_payload: dict[str, str] | None = None
        try:
            internal_prompt_payload = await request_character_chat_internal_prompt_payload(
                summary_client,
                target=target,
                profile_payload=profile_payload,
                example_payload=example_payload,
                dialogue_items=dialogue_items,
                summary_context_lines=summary_context_lines,
                inventory_item=inventory_item,
                relation_context_lines=relation_context_lines,
                scene_context_lines=scene_context_lines,
            )
        except Exception as exc:
            logger.warning(
                "story_agent_character_chat_prompt_keep_old product_id=%s scope_key=%s error=%s",
                product_id,
                character_key,
                repr(exc)[:200],
            )
            if verbose:
                print(f"[character-chat-prompt-skip] product_id={product_id} character={character_key} error={repr(exc)[:160]}")
        if internal_prompt_payload:
            internal_prompt_payload = {
                "character_key": character_key,
                "display_name": str(profile_payload.get("display_name") or "").strip(),
                **internal_prompt_payload,
            }

        profile_source_hash = build_rp_profile_source_hash(
            character_key=character_key,
            inventory_item=inventory_item,
            dialogue_items=dialogue_items,
            summary_context_lines=summary_context_lines,
            relation_context_lines=relation_context_lines,
        )
        examples_source_hash = build_rp_examples_source_hash(
            character_key=character_key,
            inventory_item=inventory_item,
            example_payload=example_payload,
            summary_context_lines=summary_context_lines,
            relation_context_lines=relation_context_lines,
        )
        internal_prompt_source_hash = ""
        if internal_prompt_payload:
            internal_prompt_source_hash = build_character_chat_internal_prompt_source_hash(
                character_key=character_key,
                inventory_item=inventory_item,
                profile_payload=profile_payload,
                example_payload=example_payload,
                dialogue_items=dialogue_items,
                summary_context_lines=summary_context_lines,
                relation_context_lines=relation_context_lines,
                scene_context_lines=scene_context_lines,
            )
        with work_cursor(conn) as cur:
            _, profile_inserted = upsert_summary(
                cur,
                product_id=product_id,
                summary_type="character_rp_profile",
                scope_key=character_key,
                source_hash=profile_source_hash,
                source_doc_count=len(dialogue_items),
                summary_text=json.dumps(profile_payload, ensure_ascii=False),
            )
            _, examples_inserted = upsert_summary(
                cur,
                product_id=product_id,
                summary_type="character_rp_examples",
                scope_key=character_key,
                source_hash=examples_source_hash,
                source_doc_count=len(example_payload["examples"]),
                summary_text=json.dumps(example_payload, ensure_ascii=False),
            )
            if internal_prompt_payload:
                upsert_summary(
                    cur,
                    product_id=product_id,
                    summary_type="character_chat_internal_prompt",
                    scope_key=character_key,
                    source_hash=internal_prompt_source_hash,
                    source_doc_count=len(dialogue_items),
                    summary_text=json.dumps(internal_prompt_payload, ensure_ascii=False),
                )
        conn.commit()
        counts["profile"][0 if profile_inserted else 1] += 1
        counts["examples"][0 if examples_inserted else 1] += 1

    successful_profile_count = int(counts["profile"][0]) + int(counts["profile"][1])
    if successful_profile_count > 0:
        with work_cursor(conn) as cur:
            deactivate_missing_active_scopes(cur, product_id, "character_rp_profile", valid_scope_keys)
            deactivate_missing_active_scopes(cur, product_id, "character_rp_examples", valid_scope_keys)
            deactivate_missing_active_scopes(cur, product_id, "character_chat_internal_prompt", valid_scope_keys)
        conn.commit()
    return {key: (value[0], value[1]) for key, value in counts.items()}


def build_empty_delta_rp_counts() -> dict[str, object]:
    return {
        "profile": [0, 0],
        "examples": [0, 0],
        "deactivated_profile_count": 0,
        "deactivated_examples_count": 0,
        "keep_old_dialogue_missing_count": 0,
        "keep_old_examples_missing_count": 0,
    }


def is_expected_story_asset_provider_error(exc: BaseException) -> bool:
    return isinstance(
        exc,
        (asyncio.TimeoutError, HTTPStatusError, RequestError, json.JSONDecodeError),
    )


async def build_rp_summaries_delta(
    conn,
    *,
    product_id: int,
    affected_scope_keys: set[str],
    episode_rows: list[dict[str, object]],
    episode_texts_by_no: dict[int, str],
    summary_client: AsyncClient | None,
    inventory_map: dict[str, dict[str, object]],
    relation_map: dict[str, list[dict[str, object]]],
    historical_inventory_state_map: dict[str, dict[str, object]] | None = None,
    raise_unexpected_errors: bool = False,
    verbose: bool = False,
) -> dict[str, object]:
    counts = build_empty_delta_rp_counts()
    if not affected_scope_keys:
        return counts

    provider_available = bool(
        summary_client is not None
        and OPENROUTER_API_KEY
        and RP_OPENROUTER_MODEL
    )
    scene_context_lines_by_scope = (
        load_character_chat_scene_context_lines_by_scope(
            conn,
            product_id=product_id,
        )
        if provider_available
        else {}
    )
    with work_cursor(conn) as cur:
        existing_profile_rows_by_scope = fetch_active_summary_state_map(
            cur=cur,
            product_id=product_id,
            summary_type="character_rp_profile",
        )
        existing_example_rows_by_scope = fetch_active_summary_state_map(
            cur=cur,
            product_id=product_id,
            summary_type="character_rp_examples",
        )
    source_scope_key_map = build_inventory_source_scope_key_map(inventory_map or {})
    selected_scope_keys: set[str] = set()
    for selected_target in build_inventory_rp_targets(inventory_map or {}):
        selected_scope_key = str(selected_target.get("character_key") or "").strip()
        if not selected_scope_key:
            continue
        selected_scope_keys.update(
            build_inventory_scope_alias_keys(
                selected_scope_key,
                dict((inventory_map or {}).get(selected_scope_key) or {}),
            )
        )
    processed_scope_keys: set[str] = set()
    for scope_key in sorted(affected_scope_keys):
        raw_scope_key = str(scope_key or "").strip()
        scope_key = source_scope_key_map.get(raw_scope_key, raw_scope_key)
        if not scope_key or scope_key in processed_scope_keys:
            continue
        processed_scope_keys.add(scope_key)
        if (
            raw_scope_key not in selected_scope_keys
            and scope_key not in selected_scope_keys
        ):
            logger.info(
                "story_agent_delta_rp_keep_old product_id=%s scope_key=%s reason=%s",
                product_id,
                scope_key,
                "target_limit",
            )
            continue
        inventory_item = dict(inventory_map.get(scope_key) or {})
        if not inventory_item:
            logger.info(
                "story_agent_delta_rp_keep_old product_id=%s scope_key=%s reason=inventory_missing",
                product_id,
                scope_key,
            )
            continue

        if not is_batch_rp_candidate(inventory_item):
            logger.info(
                "story_agent_delta_rp_keep_old product_id=%s scope_key=%s reason=not_current_candidate",
                product_id,
                scope_key,
            )
            continue

        target = dict(build_inventory_rp_target(scope_key=scope_key, inventory_item=inventory_item) or {})
        if not target:
            continue
        target = attach_competing_speaker_anchors(
            target,
            current_scope_key=scope_key,
            inventory_map=inventory_map,
        )
        skip_reason = get_rp_target_skip_reason(target)
        if skip_reason:
            logger.info(
                "story_agent_delta_rp_keep_old product_id=%s scope_key=%s reason=%s",
                product_id,
                scope_key,
                skip_reason,
            )
            counts["keep_old_examples_missing_count"] += 1
            continue

        exact_profile_row = dict(existing_profile_rows_by_scope.get(scope_key) or {})
        exact_example_row = dict(existing_example_rows_by_scope.get(scope_key) or {})
        exact_profile_payload = dict(exact_profile_row.get("payload") or {})
        exact_example_payload = dict(exact_example_row.get("payload") or {})
        canonical_profile_ready = (
            str(exact_profile_payload.get("character_key") or "").strip() == scope_key
        )
        canonical_examples_ready = (
            str(exact_example_payload.get("character_key") or "").strip() == scope_key
            and bool(build_rp_dialogue_items_from_example_payload(exact_example_payload))
        )
        if canonical_profile_ready and canonical_examples_ready:
            counts["profile"][1] += 1
            counts["examples"][1] += 1
            continue

        existing_profile_row: dict[str, object] = {}
        existing_example_row: dict[str, object] = {}
        allowed_alias_keys = {
            alias_key
            for alias_key, owner_scope_key in source_scope_key_map.items()
            if owner_scope_key == scope_key
        }
        if not canonical_profile_ready and not canonical_examples_ready:
            for alias_key in build_inventory_scope_alias_key_candidates(
                scope_key,
                inventory_item,
            ):
                if alias_key == scope_key or alias_key not in allowed_alias_keys:
                    continue
                legacy_profile_row = dict(existing_profile_rows_by_scope.get(alias_key) or {})
                legacy_example_row = dict(existing_example_rows_by_scope.get(alias_key) or {})
                legacy_profile_payload = dict(legacy_profile_row.get("payload") or {})
                legacy_example_payload = dict(legacy_example_row.get("payload") or {})
                if (
                    str(legacy_profile_payload.get("character_key") or "").strip() == alias_key
                    and str(legacy_example_payload.get("character_key") or "").strip() == alias_key
                    and build_rp_dialogue_items_from_example_payload(legacy_example_payload)
                ):
                    existing_profile_row = legacy_profile_row
                    existing_example_row = legacy_example_row
                    break
        if (
            not existing_profile_row
            and not existing_example_row
            and not canonical_profile_ready
            and not canonical_examples_ready
        ):
            current_identity_aliases = (
                _character_inventory_continuity_aliases(scope_key, inventory_item)
                & allowed_alias_keys
            ) - {scope_key}
            historical_candidates = sorted(
                (historical_inventory_state_map or {}).items(),
                key=lambda item: int(dict(item[1] or {}).get("summary_id") or 0),
                reverse=True,
            )
            for historical_scope_key, historical_state in historical_candidates:
                historical_scope_key = str(historical_scope_key or "").strip()
                if not historical_scope_key or historical_scope_key == scope_key:
                    continue
                historical_payload = dict(
                    dict(historical_state or {}).get("payload") or {}
                )
                historical_identity_aliases = (
                    _character_inventory_continuity_aliases(
                        historical_scope_key,
                        historical_payload,
                    )
                    - {historical_scope_key}
                )
                if not current_identity_aliases.intersection(
                    historical_identity_aliases
                ):
                    continue
                legacy_profile_row = dict(
                    existing_profile_rows_by_scope.get(historical_scope_key) or {}
                )
                legacy_example_row = dict(
                    existing_example_rows_by_scope.get(historical_scope_key) or {}
                )
                legacy_profile_payload = dict(
                    legacy_profile_row.get("payload") or {}
                )
                legacy_example_payload = dict(
                    legacy_example_row.get("payload") or {}
                )
                if (
                    str(legacy_profile_payload.get("character_key") or "").strip()
                    == historical_scope_key
                    and str(legacy_example_payload.get("character_key") or "").strip()
                    == historical_scope_key
                    and build_rp_dialogue_items_from_example_payload(
                        legacy_example_payload
                    )
                ):
                    existing_profile_row = legacy_profile_row
                    existing_example_row = legacy_example_row
                    logger.info(
                        "story_agent_delta_rp_history_bridge product_id=%s current_scope_key=%s historical_scope_key=%s",
                        product_id,
                        scope_key,
                        historical_scope_key,
                    )
                    break
        existing_profile_payload = dict(existing_profile_row.get("payload") or {})
        existing_example_payload = dict(existing_example_row.get("payload") or {})
        existing_dialogue_items = build_rp_dialogue_items_from_example_payload(existing_example_payload)
        if existing_profile_payload and existing_example_payload and existing_dialogue_items:
            profile_payload = {
                **existing_profile_payload,
                "character_key": scope_key,
                "display_name": str(
                    existing_profile_payload.get("display_name")
                    or target.get("display_name")
                    or target.get("reference_name")
                    or ""
                ).strip(),
            }
            example_payload = {
                **existing_example_payload,
                "character_key": scope_key,
            }
            profile_source_hash = build_compound_summary_source_hash(
                CHARACTER_RP_PROFILE_FORMAT_VERSION,
                [
                    "alias_bridge_v2",
                    scope_key,
                    str(existing_profile_row.get("scope_key") or ""),
                    str(existing_profile_row.get("source_hash") or ""),
                ],
            )
            examples_source_hash = build_compound_summary_source_hash(
                CHARACTER_RP_EXAMPLES_FORMAT_VERSION,
                [
                    "alias_bridge_v2",
                    scope_key,
                    str(existing_example_row.get("scope_key") or ""),
                    str(existing_example_row.get("source_hash") or ""),
                ],
            )
            with work_cursor(conn) as cur:
                _, profile_inserted = upsert_summary(
                    cur,
                    product_id=product_id,
                    summary_type="character_rp_profile",
                    scope_key=scope_key,
                    source_hash=profile_source_hash,
                    source_doc_count=1,
                    summary_text=json.dumps(profile_payload, ensure_ascii=False),
                )
                _, examples_inserted = upsert_summary(
                    cur,
                    product_id=product_id,
                    summary_type="character_rp_examples",
                    scope_key=scope_key,
                    source_hash=examples_source_hash,
                    source_doc_count=len(existing_dialogue_items),
                    summary_text=json.dumps(example_payload, ensure_ascii=False),
                )
            counts["profile"][0 if profile_inserted else 1] += 1
            counts["examples"][0 if examples_inserted else 1] += 1
            continue

        if not provider_available:
            logger.info(
                "story_agent_delta_rp_keep_old product_id=%s scope_key=%s reason=provider_unavailable",
                product_id,
                scope_key,
            )
            continue

        aliases = [str(alias).strip() for alias in (target.get("aliases") or []) if str(alias).strip()]
        summary_context_lines = collect_rp_summary_context_lines(target, episode_rows)
        relation_context_lines = build_rp_relation_context_lines(
            character_key=scope_key,
            relation_map=relation_map,
        )
        scene_context_lines = scene_context_lines_by_scope.get(scope_key, [])

        direct_dialogue_items = collect_rule_based_rp_dialogue_items_by_episode(target, episode_texts_by_no)
        dialogue_items: list[dict[str, object]] = []
        direct_voice_quality = build_direct_voice_evidence_quality(target, episode_texts_by_no)
        if not bool(direct_voice_quality.get("strict_chat_ready")):
            try:
                llm_dialogue_items = await collect_llm_rp_dialogue_items(
                    summary_client,
                    target=target,
                    episode_texts_by_no=episode_texts_by_no,
                    aliases=aliases,
                )
            except Exception as exc:
                if raise_unexpected_errors and not is_expected_story_asset_provider_error(exc):
                    raise
                if verbose:
                    print(f"[rp-delta-dialogue-skip] product_id={product_id} character={scope_key} error={str(exc)[:160]}")
                llm_dialogue_items = []
            dialogue_items = dedupe_rp_dialogue_items(
                [*direct_dialogue_items, *llm_dialogue_items],
                limit=80,
            )
            dialogue_items = mark_rp_example_candidates(dialogue_items, aliases)
            if sum(bool(item.get("is_example_candidate")) for item in dialogue_items) < RP_PROFILE_MIN_EXAMPLE_TEXTS:
                logger.info(
                    "story_agent_delta_rp_keep_old product_id=%s scope_key=%s reason=%s status=%s",
                    product_id,
                    scope_key,
                    "direct_voice_not_ready",
                    str(direct_voice_quality.get("status") or "unknown"),
                )
                counts["keep_old_dialogue_missing_count"] += 1
                continue
        else:
            dialogue_items = direct_dialogue_items

        dialogue_items = dedupe_rp_dialogue_items(dialogue_items, limit=80)
        dialogue_items = mark_rp_example_candidates(dialogue_items, aliases)
        if not dialogue_items:
            logger.info(
                "story_agent_delta_rp_keep_old product_id=%s scope_key=%s reason=%s",
                product_id,
                scope_key,
                "dialogue_items_missing",
            )
            counts["keep_old_dialogue_missing_count"] += 1
            continue

        try:
            payload = await request_rp_profile_payload(
                summary_client,
                target=target,
                dialogue_items=dialogue_items,
                summary_context_lines=summary_context_lines,
                inventory_item=inventory_item,
                relation_context_lines=relation_context_lines,
            )
        except Exception as exc:
            if raise_unexpected_errors and not is_expected_story_asset_provider_error(exc):
                raise
            if verbose:
                print(f"[rp-delta-skip] product_id={product_id} character={scope_key} error={str(exc)[:160]}")
            continue
        if not payload:
            continue

        profile_payload = {
            "character_key": scope_key,
            "display_name": str(target.get("display_name") or "").strip() or str(target.get("reference_name") or "").strip(),
            "aliases": [str(alias).strip() for alias in (target.get("aliases") or []) if str(alias).strip()],
            "speech_style": payload.get("speech_style") or {},
            "personality_core": [str(item).strip() for item in (payload.get("personality_core") or []) if str(item).strip()][:2],
            "baseline_attitude": str(payload.get("baseline_attitude") or "").strip() or "무난",
        }
        example_texts = select_rp_example_texts(payload, dialogue_items, aliases)
        if not has_enough_rp_example_texts(example_texts):
            logger.info(
                "story_agent_delta_rp_keep_old product_id=%s scope_key=%s reason=%s selected_examples=%s min_examples=%s",
                product_id,
                scope_key,
                "example_texts_below_min",
                len(example_texts),
                RP_PROFILE_MIN_EXAMPLE_TEXTS,
            )
            counts["keep_old_examples_missing_count"] += 1
            continue

        example_payload = {
            "character_key": scope_key,
            "examples": [],
        }
        for example_text in example_texts:
            matched_item = next((item for item in dialogue_items if str(item.get("text") or "").strip() == example_text), None)
            example_payload["examples"].append(
                {
                    "episode_no": int((matched_item or {}).get("episode_no") or 0),
                    "source_kind": str((matched_item or {}).get("kind") or "dialogue"),
                    "text": example_text,
                    "confidence": 0.9 if matched_item else 0.7,
                }
            )
        internal_prompt_payload: dict[str, str] | None = None
        try:
            internal_prompt_payload = await request_character_chat_internal_prompt_payload(
                summary_client,
                target=target,
                profile_payload=profile_payload,
                example_payload=example_payload,
                dialogue_items=dialogue_items,
                summary_context_lines=summary_context_lines,
                inventory_item=inventory_item,
                relation_context_lines=relation_context_lines,
                scene_context_lines=scene_context_lines,
            )
        except Exception as exc:
            if raise_unexpected_errors and not is_expected_story_asset_provider_error(exc):
                raise
            logger.warning(
                "story_agent_delta_character_chat_prompt_keep_old product_id=%s scope_key=%s error=%s",
                product_id,
                scope_key,
                repr(exc)[:200],
            )
            if verbose:
                print(f"[character-chat-delta-prompt-skip] product_id={product_id} character={scope_key} error={repr(exc)[:160]}")
        if internal_prompt_payload:
            internal_prompt_payload = {
                "character_key": scope_key,
                "display_name": str(profile_payload.get("display_name") or "").strip(),
                **internal_prompt_payload,
            }

        profile_source_hash = build_rp_profile_source_hash(
            character_key=scope_key,
            inventory_item=inventory_item,
            dialogue_items=dialogue_items,
            summary_context_lines=summary_context_lines,
            relation_context_lines=relation_context_lines,
        )
        examples_source_hash = build_rp_examples_source_hash(
            character_key=scope_key,
            inventory_item=inventory_item,
            example_payload=example_payload,
            summary_context_lines=summary_context_lines,
            relation_context_lines=relation_context_lines,
        )
        internal_prompt_source_hash = ""
        if internal_prompt_payload:
            internal_prompt_source_hash = build_character_chat_internal_prompt_source_hash(
                character_key=scope_key,
                inventory_item=inventory_item,
                profile_payload=profile_payload,
                example_payload=example_payload,
                dialogue_items=dialogue_items,
                summary_context_lines=summary_context_lines,
                relation_context_lines=relation_context_lines,
                scene_context_lines=scene_context_lines,
            )

        with work_cursor(conn) as cur:
            profile_inserted = False
            examples_inserted = False
            if not canonical_profile_ready:
                _, profile_inserted = upsert_summary(
                    cur,
                    product_id=product_id,
                    summary_type="character_rp_profile",
                    scope_key=scope_key,
                    source_hash=profile_source_hash,
                    source_doc_count=len(dialogue_items),
                    summary_text=json.dumps(profile_payload, ensure_ascii=False),
                )
            if not canonical_examples_ready:
                _, examples_inserted = upsert_summary(
                    cur,
                    product_id=product_id,
                    summary_type="character_rp_examples",
                    scope_key=scope_key,
                    source_hash=examples_source_hash,
                    source_doc_count=len(example_payload["examples"]),
                    summary_text=json.dumps(example_payload, ensure_ascii=False),
                )
            if internal_prompt_payload:
                upsert_summary(
                    cur,
                    product_id=product_id,
                    summary_type="character_chat_internal_prompt",
                    scope_key=scope_key,
                    source_hash=internal_prompt_source_hash,
                    source_doc_count=len(dialogue_items),
                    summary_text=json.dumps(internal_prompt_payload, ensure_ascii=False),
                )
        counts["profile"][0 if profile_inserted else 1] += 1
        counts["examples"][0 if examples_inserted else 1] += 1

    return counts


async def build_character_chat_opening_summaries(
    conn,
    *,
    product_id: int,
    episode_rows: list[dict[str, object]],
    summary_client: AsyncClient | None,
    inventory_map: dict[str, dict[str, object]],
    relation_map: dict[str, list[dict[str, object]]],
    affected_scope_keys: set[str] | None = None,
    cleanup_missing_scopes: bool = True,
    verbose: bool = False,
) -> tuple[int, int]:
    if summary_client is None or not OPENROUTER_API_KEY or not EPISODE_SCENE_EXTRACTION_OPENROUTER_MODEL:
        return 0, 0

    with work_cursor(conn) as cur:
        profile_rows_by_scope = fetch_active_summary_state_map(
            cur=cur,
            product_id=product_id,
            summary_type="character_rp_profile",
        )
        example_rows_by_scope = fetch_active_summary_state_map(
            cur=cur,
            product_id=product_id,
            summary_type="character_rp_examples",
        )
        internal_prompt_rows_by_scope = fetch_active_summary_state_map(
            cur=cur,
            product_id=product_id,
            summary_type="character_chat_internal_prompt",
        )

    scene_context_lines_by_scope = load_character_chat_scene_context_lines_by_scope(
        conn,
        product_id=product_id,
    )
    source_scope_key_map = build_inventory_source_scope_key_map(inventory_map or {})
    normalized_affected_scope_keys: set[str] | None = None
    if affected_scope_keys is not None:
        normalized_affected_scope_keys = {
            source_scope_key_map.get(str(scope_key or "").strip(), str(scope_key or "").strip())
            for scope_key in affected_scope_keys
            if str(scope_key or "").strip()
        }

    inserted_count = 0
    reused_count = 0
    valid_scope_keys: set[str] = set()
    for scope_key, inventory_item in sorted((inventory_map or {}).items()):
        scope_key = str(scope_key or "").strip()
        if not scope_key:
            continue
        if normalized_affected_scope_keys is not None and scope_key not in normalized_affected_scope_keys:
            continue
        inventory_item = dict(inventory_item or {})
        if not is_batch_rp_candidate(inventory_item):
            continue
        target = dict(build_inventory_rp_target(scope_key=scope_key, inventory_item=inventory_item) or {})
        if not target:
            continue
        target = attach_competing_speaker_anchors(
            target,
            current_scope_key=scope_key,
            inventory_map=inventory_map,
        )
        if get_rp_target_skip_reason(target):
            continue
        profile_row = fetch_summary_state_for_inventory_alias(
            profile_rows_by_scope,
            scope_key=scope_key,
            inventory_item=inventory_item,
            allowed_alias_keys={
                alias_key
                for alias_key, owner_scope_key in source_scope_key_map.items()
                if owner_scope_key == scope_key
            },
        )
        example_row = fetch_summary_state_for_inventory_alias(
            example_rows_by_scope,
            scope_key=scope_key,
            inventory_item=inventory_item,
            allowed_alias_keys={
                alias_key
                for alias_key, owner_scope_key in source_scope_key_map.items()
                if owner_scope_key == scope_key
            },
        )
        internal_prompt_row = fetch_summary_state_for_inventory_alias(
            internal_prompt_rows_by_scope,
            scope_key=scope_key,
            inventory_item=inventory_item,
            allowed_alias_keys={
                alias_key
                for alias_key, owner_scope_key in source_scope_key_map.items()
                if owner_scope_key == scope_key
            },
        )
        scene_context_lines = scene_context_lines_by_scope.get(scope_key, [])
        if not profile_row or not example_row or not internal_prompt_row or not scene_context_lines:
            continue

        display_name = str(target.get("display_name") or target.get("reference_name") or "").strip()
        profile_payload = canonicalize_character_chat_payload_scope(
            dict(profile_row.get("payload") or {}),
            scope_key=scope_key,
            display_name=display_name,
        )
        example_payload = canonicalize_character_chat_payload_scope(
            dict(example_row.get("payload") or {}),
            scope_key=scope_key,
            display_name=display_name,
        )
        internal_prompt_payload = canonicalize_character_chat_payload_scope(
            dict(internal_prompt_row.get("payload") or {}),
            scope_key=scope_key,
            display_name=display_name,
        )
        if not profile_payload or not example_payload or not internal_prompt_payload:
            continue

        summary_context_lines = collect_rp_summary_context_lines(target, episode_rows)
        relation_context_lines = build_rp_relation_context_lines(
            character_key=scope_key,
            relation_map=relation_map,
        )
        source_hash = build_character_chat_opening_source_hash(
            character_key=scope_key,
            inventory_item=inventory_item,
            profile_row=profile_row,
            examples_row=example_row,
            internal_prompt_row=internal_prompt_row,
            summary_context_lines=summary_context_lines,
            relation_context_lines=relation_context_lines,
            scene_context_lines=scene_context_lines,
        )
        reused_existing = False
        with work_cursor(conn) as cur:
            existing = fetch_existing_summary(
                cur=cur,
                product_id=product_id,
                summary_type="character_chat_opening_v1",
                scope_key=scope_key,
                source_hash=source_hash,
            )
            if existing and _is_character_chat_opening_row_ready(existing, scope_key=scope_key):
                activate_existing_summary(
                    cur,
                    int(existing["summary_id"]),
                    product_id,
                    "character_chat_opening_v1",
                    scope_key,
                )
                reused_existing = True
        if reused_existing:
            conn.commit()
            valid_scope_keys.add(scope_key)
            reused_count += 1
            continue

        try:
            opening_payload = await request_character_chat_opening_payload(
                summary_client,
                scope_key=scope_key,
                target=target,
                profile_payload=profile_payload,
                example_payload=example_payload,
                internal_prompt_payload=internal_prompt_payload,
                summary_context_lines=summary_context_lines,
                inventory_item=inventory_item,
                relation_context_lines=relation_context_lines,
                scene_context_lines=scene_context_lines,
            )
        except Exception as exc:
            logger.warning(
                "story_agent_character_chat_opening_keep_old product_id=%s scope_key=%s error=%s",
                product_id,
                scope_key,
                str(exc)[:200],
            )
            if verbose:
                print(f"[character-chat-opening-skip] product_id={product_id} character={scope_key} error={str(exc)[:160]}")
            continue
        if not opening_payload:
            continue

        valid_scope_keys.add(scope_key)
        with work_cursor(conn) as cur:
            _, inserted = upsert_summary(
                cur,
                product_id=product_id,
                summary_type="character_chat_opening_v1",
                scope_key=scope_key,
                source_hash=source_hash,
                source_doc_count=len(scene_context_lines),
                summary_text=json.dumps(opening_payload, ensure_ascii=False),
            )
        conn.commit()
        if inserted:
            inserted_count += 1
        else:
            reused_count += 1

    if cleanup_missing_scopes and (inserted_count + reused_count) > 0:
        with work_cursor(conn) as cur:
            deactivate_missing_active_scopes(cur, product_id, "character_chat_opening_v1", valid_scope_keys)
        conn.commit()
    return inserted_count, reused_count


async def build_episode_character_signals_summaries(
    conn,
    *,
    product_id: int,
    episode_rows: list[dict[str, object]],
    summary_client: AsyncClient | None,
    cleanup_missing_scopes: bool = True,
    verbose: bool = False,
) -> tuple[int, int]:
    if summary_client is None:
        return 0, 0
    provider_available = is_episode_character_signals_provider_available()

    inserted_count = 0
    reused_count = 0
    valid_scope_keys: set[str] = set()
    for row in episode_rows:
        summary_id = int(row.get("summary_id") or 0)
        episode_no = int(row.get("episode_from") or 0)
        summary_text = str(row.get("summary_text") or "").strip()
        if not summary_id or episode_no <= 0 or not summary_text:
            continue
        scope_key = str(row.get("scope_key") or "").strip()
        if not scope_key:
            continue
        valid_scope_keys.add(scope_key)
        source_hash = build_compound_summary_source_hash(
            EPISODE_CHARACTER_SIGNALS_FORMAT_VERSION,
            [
                f"{summary_id}:{str(row.get('source_hash') or '').strip()}",
                build_rp_reasoning_signature(),
            ],
        )
        existing_summary_id = 0
        with work_cursor(conn) as cur:
            existing = fetch_existing_summary(
                cur=cur,
                product_id=product_id,
                summary_type="episode_character_signals",
                scope_key=scope_key,
                source_hash=source_hash,
            )
            if existing:
                existing_summary_id = int(existing["summary_id"])
                activate_existing_summary(
                    cur,
                    existing_summary_id,
                    product_id,
                    "episode_character_signals",
                    scope_key,
                )
        if existing_summary_id:
            conn.commit()
            reused_count += 1
            continue
        if not provider_available:
            if verbose:
                print(
                    f"[character-signals-keep-old] product_id={product_id} "
                    f"episode_no={episode_no} reason=provider_unavailable"
                )
            continue

        try:
            if verbose:
                print(
                    f"[character-signals-start] product_id={product_id} episode_no={episode_no} "
                    f"signature={build_rp_reasoning_signature()}"
                )
            payload = await request_episode_character_signals_payload(
                summary_client,
                row={
                    "episode_no": episode_no,
                    "title": "",
                    "episode_title": parse_summary_text(summary_text).get("header") or "",
                },
                summary_text=summary_text,
            )
        except Exception as exc:
            if verbose:
                if isinstance(exc, EpisodeCharacterSignalsParseError):
                    print(
                        f"[character-signals-parse] product_id={product_id} episode_no={episode_no} "
                        f"model={exc.model} request_id={exc.request_id or '-'} "
                        f"json_parse_ok={'Y' if exc.json_parse_ok else 'N'} "
                        f"line_parse_ok={'Y' if exc.line_parse_ok else 'N'} "
                        f"char_count={exc.char_count} rel_count={exc.rel_count} hook_count={exc.hook_count} "
                        f"raw_sha256={exc.raw_sha256}"
                    )
                    print(
                        f"[character-signals-raw] product_id={product_id} episode_no={episode_no} "
                        f"preview={json.dumps(exc.raw_preview, ensure_ascii=False)}"
                    )
                print(f"[character-signals-skip] product_id={product_id} episode_no={episode_no} error={str(exc)[:240]}")
            with work_cursor(conn) as cur:
                deactivate_active_scope(
                    cur,
                    product_id=product_id,
                    summary_type="episode_character_signals",
                    scope_key=scope_key,
                )
            conn.commit()
            raise
        normalized_payload = normalize_episode_character_signals_payload(payload, episode_no=episode_no)
        with work_cursor(conn) as cur:
            _, inserted = upsert_summary(
                cur,
                product_id=product_id,
                summary_type="episode_character_signals",
                scope_key=scope_key,
                source_hash=source_hash,
                source_doc_count=1,
                summary_text=json.dumps(normalized_payload, ensure_ascii=False),
                episode_from=episode_no,
                episode_to=episode_no,
            )
        conn.commit()
        if inserted:
            inserted_count += 1
        else:
            reused_count += 1

    if cleanup_missing_scopes:
        with work_cursor(conn) as cur:
            deactivate_missing_active_scopes(cur, product_id, "episode_character_signals", valid_scope_keys)
        conn.commit()
    return inserted_count, reused_count


def build_episode_scene_canonical_character_packet(
    inventory_map: dict[str, dict[str, object]],
    *,
    limit: int = 24,
) -> dict[str, list[dict[str, object]]]:
    rows: list[dict[str, object]] = []
    for scope_key, item in (inventory_map or {}).items():
        scope_key = str(scope_key or item.get("canonical_character_key") or "").strip()
        display_name = str(item.get("display_name") or "").strip()
        if not scope_key or not display_name:
            continue
        if str(item.get("entity_kind") or "person").strip().lower() != "person":
            continue
        aliases = [
            str(alias).strip()
            for alias in list(item.get("aliases") or [])
            if str(alias).strip()
        ][:8]
        rows.append(
            {
                "scope_key": scope_key,
                "display_name": display_name,
                "aliases": aliases,
                "work_role": str(item.get("work_role") or "").strip(),
                "is_protagonist": bool(item.get("is_protagonist"))
                or str(item.get("work_role") or "").strip() == "main_protagonist",
                "first_seen_episode_no": int(item.get("first_seen_episode_no") or 0),
                "distinct_episode_count": int(item.get("distinct_episode_count") or 0),
            }
        )
    rows.sort(
        key=lambda item: (
            0 if bool(item.get("is_protagonist")) else 1,
            int(item.get("first_seen_episode_no") or 999999),
            -int(item.get("distinct_episode_count") or 0),
            str(item.get("display_name") or ""),
        )
    )
    return {"characters": rows[:limit]}


def build_episode_scene_extraction_source_hash(
    row: dict[str, object],
    canonical_character_packet: object | None,
) -> str:
    return build_compound_summary_source_hash(
        EPISODE_SCENE_EXTRACTION_FORMAT_VERSION,
        [
            f"{int(row.get('summary_id') or 0)}:{str(row.get('source_hash') or '').strip()}",
            json.dumps(canonical_character_packet or {"characters": []}, ensure_ascii=False, sort_keys=True),
        ],
    )


def extract_episode_scene_character_scope_keys(
    payload: dict[str, object] | None,
) -> set[str]:
    scope_keys: set[str] = set()
    for scene in list(dict(payload or {}).get("scenes") or []):
        if not isinstance(scene, dict):
            continue
        scope_keys.update(
            str(item.get("scope_key") or "").strip()
            for item in list(scene.get("participants") or [])
            if isinstance(item, dict) and str(item.get("scope_key") or "").strip()
        )
        scope_keys.update(
            str(item.get("actor_scope_key") or "").strip()
            for item in list(scene.get("action_ownership") or [])
            if isinstance(item, dict)
            and str(item.get("actor_scope_key") or "").strip()
        )
    return scope_keys


async def build_episode_scene_extraction_summaries(
    conn,
    *,
    product_id: int,
    product_title: str,
    episode_rows: list[dict[str, object]],
    episode_texts_by_no: dict[int, str],
    summary_client: AsyncClient | None,
    canonical_character_packet: object | None,
    required_scope_keys_by_episode_no: dict[int, set[str]] | None = None,
    cleanup_missing_scopes: bool = True,
    raise_unexpected_errors: bool = False,
    verbose: bool = False,
) -> tuple[int, int]:
    if summary_client is None or not OPENROUTER_API_KEY or not EPISODE_SCENE_EXTRACTION_OPENROUTER_MODEL:
        return 0, 0
    packet_characters = (
        list(canonical_character_packet.get("characters") or [])
        if isinstance(canonical_character_packet, dict)
        else []
    )
    if not packet_characters:
        return 0, 0

    inserted_count = 0
    reused_count = 0
    valid_scope_keys: set[str] = set()
    for row in episode_rows:
        summary_id = int(row.get("summary_id") or 0)
        episode_no = int(row.get("episode_from") or row.get("episode_no") or 0)
        normalized_text = str(episode_texts_by_no.get(episode_no) or "").strip()
        scope_key = str(row.get("scope_key") or "").strip()
        required_scope_keys = set(
            (required_scope_keys_by_episode_no or {}).get(episode_no) or set()
        )
        preserved_scope_keys: set[str] = set()
        if not summary_id or episode_no <= 0 or not normalized_text or not scope_key:
            continue
        valid_scope_keys.add(scope_key)
        source_hash = build_episode_scene_extraction_source_hash(row, canonical_character_packet)
        existing_summary_id = 0
        replace_existing_summary_id = 0
        with work_cursor(conn) as cur:
            existing = fetch_existing_summary(
                cur=cur,
                product_id=product_id,
                summary_type="episode_scene_extraction",
                scope_key=scope_key,
                source_hash=source_hash,
            )
            active = fetch_active_summary_by_scope(
                cur=cur,
                product_id=product_id,
                summary_type="episode_scene_extraction",
                scope_key=scope_key,
            )
            active_payload = extract_json_object(
                str(dict(active or {}).get("summary_text") or "")
            ) or {}
            if _is_usable_episode_scene_payload(active_payload):
                preserved_scope_keys.update(
                    extract_episode_scene_character_scope_keys(active_payload)
                )
            if existing:
                existing_payload = extract_json_object(str(existing.get("summary_text") or "")) or {}
                existing_scope_keys = extract_episode_scene_character_scope_keys(
                    existing_payload
                )
                existing_payload_usable = _is_usable_episode_scene_payload(
                    existing_payload
                )
                required_existing_scope_keys = required_scope_keys | preserved_scope_keys
                if existing_payload_usable and required_existing_scope_keys.issubset(existing_scope_keys):
                    existing_summary_id = int(existing["summary_id"])
                    activate_existing_summary(
                        cur,
                        existing_summary_id,
                        product_id,
                        "episode_scene_extraction",
                        scope_key,
                    )
                else:
                    replace_existing_summary_id = int(existing["summary_id"])
                    if existing_payload_usable:
                        preserved_scope_keys.update(existing_scope_keys)
        if existing_summary_id:
            conn.commit()
            reused_count += 1
            continue

        try:
            if verbose:
                print(
                    f"[episode-scene-start] product_id={product_id} episode_no={episode_no} "
                    f"model={EPISODE_SCENE_EXTRACTION_OPENROUTER_MODEL}"
                )
            payload = await request_episode_scene_extraction_payload(
                summary_client,
                product_title=product_title,
                episode_no=episode_no,
                episode_title=parse_summary_text(str(row.get("summary_text") or "")).get("header") or "",
                normalized_text=normalized_text,
                canonical_character_packet=canonical_character_packet,
            )
        except Exception as exc:
            if raise_unexpected_errors and not is_expected_story_asset_provider_error(exc):
                raise
            logger.warning(
                "story_agent_scene_extraction_failed product_id=%s episode_no=%s error=%s",
                product_id,
                episode_no,
                str(exc)[:240],
            )
            if verbose:
                print(f"[episode-scene-skip] product_id={product_id} episode_no={episode_no} error={str(exc)[:240]}")
            continue

        if not _is_usable_episode_scene_payload(payload):
            if verbose:
                issues = payload.get("validation_issues") if isinstance(payload, dict) else ["payload_not_object"]
                print(
                    f"[episode-scene-keep-old] product_id={product_id} episode_no={episode_no} "
                    f"reason=invalid_scene_payload issues={json.dumps(issues, ensure_ascii=False)[:180]}"
                )
            continue
        generated_scope_keys = extract_episode_scene_character_scope_keys(payload)
        required_output_scope_keys = required_scope_keys | preserved_scope_keys
        if not required_output_scope_keys.issubset(generated_scope_keys):
            logger.info(
                "story_agent_scene_extraction_keep_old product_id=%s episode_no=%s reason=required_scope_missing required=%s generated=%s",
                product_id,
                episode_no,
                ",".join(sorted(required_output_scope_keys)),
                ",".join(sorted(generated_scope_keys)),
            )
            continue

        with work_cursor(conn) as cur:
            if replace_existing_summary_id:
                update_existing_summary_payload(
                    cur,
                    summary_id=replace_existing_summary_id,
                    product_id=product_id,
                    summary_type="episode_scene_extraction",
                    scope_key=scope_key,
                    source_doc_count=1,
                    summary_text=json.dumps(payload, ensure_ascii=False),
                    episode_from=episode_no,
                    episode_to=episode_no,
                )
                inserted = True
            else:
                _, inserted = upsert_summary(
                    cur,
                    product_id=product_id,
                    summary_type="episode_scene_extraction",
                    scope_key=scope_key,
                    source_hash=source_hash,
                    source_doc_count=1,
                    summary_text=json.dumps(payload, ensure_ascii=False),
                    episode_from=episode_no,
                    episode_to=episode_no,
                )
        conn.commit()
        if inserted:
            inserted_count += 1
        else:
            reused_count += 1

    if cleanup_missing_scopes:
        with work_cursor(conn) as cur:
            deactivate_missing_active_scopes(cur, product_id, "episode_scene_extraction", valid_scope_keys)
        conn.commit()
    return inserted_count, reused_count


async def build_episode_scene_extraction_summaries_nonblocking(
    conn,
    **kwargs,
) -> tuple[int, int]:
    try:
        return await build_episode_scene_extraction_summaries(conn, **kwargs)
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            logger.exception(
                "story_agent_scene_extraction_rollback_failed product_id=%s",
                kwargs.get("product_id"),
            )
            raise
        logger.exception(
            "story_agent_scene_extraction_storage_failed product_id=%s error=%s",
            kwargs.get("product_id"),
            str(exc)[:240],
        )
        return 0, 0


def upsert_summary(
    cur,
    *,
    product_id: int,
    summary_type: str,
    scope_key: str,
    source_hash: str,
    source_doc_count: int,
    summary_text: str,
    episode_from: int | None = None,
    episode_to: int | None = None,
    reuse_existing: bool = True,
) -> tuple[int, bool]:
    if reuse_existing:
        existing = fetch_existing_summary(
            cur=cur,
            product_id=product_id,
            summary_type=summary_type,
            scope_key=scope_key,
            source_hash=source_hash,
        )
        if existing:
            activate_existing_summary(cur, int(existing["summary_id"]), product_id, summary_type, scope_key)
            return int(existing["summary_id"]), False

    version_no = fetch_next_summary_version_no(cur, product_id, summary_type, scope_key)
    cur.execute(
        """
        UPDATE tb_story_agent_context_summary
           SET is_active = 'N'
         WHERE product_id = %s
           AND summary_type = %s
           AND scope_key = %s
           AND is_active = 'Y'
        """,
        (product_id, summary_type, scope_key),
    )
    cur.execute(
        """
        INSERT INTO tb_story_agent_context_summary (
            product_id,
            summary_type,
            scope_key,
            episode_from,
            episode_to,
            source_hash,
            source_doc_count,
            version_no,
            is_active,
            summary_text,
            created_id
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'Y', %s, %s)
        """,
        (
            product_id,
            summary_type,
            scope_key,
            episode_from,
            episode_to,
            source_hash,
            source_doc_count,
            version_no,
            summary_text,
            settings.DB_DML_DEFAULT_ID,
        ),
    )
    return int(cur.lastrowid), True


def aggregate_character_inventory_rows(signal_rows: list[dict]) -> list[dict[str, object]]:
    inventory_map: dict[str, dict[str, object]] = {}
    for row in signal_rows:
        payload = extract_json_object(str(row.get("summary_text") or "")) or {}
        episode_no = int(payload.get("episode_no") or row.get("episode_from") or 0)
        for item in list(payload.get("mentioned_characters") or []):
            if not isinstance(item, dict):
                continue
            entity_kind = str(item.get("entity_kind") or "person").strip().lower()
            if entity_kind not in {"person", "stable_role"}:
                continue
            character_key = str(item.get("character_key") or "").strip()
            display_name = str(item.get("display_name") or "").strip()
            if not character_key or not display_name:
                continue
            current = inventory_map.setdefault(
                character_key,
                {
                    "character_key": character_key,
                    "display_name": display_name,
                    "aliases": set(),
                    "entity_kind": entity_kind,
                    "is_protagonist": parse_yes_no_flag(item.get("is_protagonist")),
                    "is_first_person": parse_yes_no_flag(item.get("is_first_person")),
                    "episode_nos": set(),
                    "summary_mention_count": 0,
                    "voice_evidence_count": 0,
                    "scene_weight_high_count": 0,
                    "scene_weight_medium_count": 0,
                    "scene_weight_low_count": 0,
                    "action_tag_counts": {},
                    "affect_tag_counts": {},
                    "relation_episode_count": 0,
                },
            )
            current["display_name"] = display_name
            current["entity_kind"] = entity_kind
            current["is_protagonist"] = parse_yes_no_flag(current["is_protagonist"]) or parse_yes_no_flag(item.get("is_protagonist"))
            current["is_first_person"] = parse_yes_no_flag(current["is_first_person"]) or parse_yes_no_flag(item.get("is_first_person"))
            for alias in list(item.get("aliases") or []):
                alias_text = str(alias).strip()
                if alias_text:
                    current["aliases"].add(alias_text)
            if episode_no > 0:
                current["episode_nos"].add(episode_no)
            current["summary_mention_count"] += 1
            if str(item.get("voice_mode") or "").strip().lower() in {"dialogue", "monologue"}:
                current["voice_evidence_count"] += 1
            scene_weight = str(item.get("scene_weight") or "").strip().lower()
            if scene_weight == "high":
                current["scene_weight_high_count"] += 1
            elif scene_weight == "medium":
                current["scene_weight_medium_count"] += 1
            else:
                current["scene_weight_low_count"] += 1
            for tag in list(item.get("action_tags") or []):
                tag_text = str(tag).strip()
                if not tag_text:
                    continue
                current["action_tag_counts"][tag_text] = int(current["action_tag_counts"].get(tag_text) or 0) + 1
            for tag in list(item.get("affect_tags") or []):
                tag_text = str(tag).strip()
                if not tag_text:
                    continue
                current["affect_tag_counts"][tag_text] = int(current["affect_tag_counts"].get(tag_text) or 0) + 1
            if list(item.get("relation_edges") or []):
                current["relation_episode_count"] += 1

    inventory_rows: list[dict[str, object]] = []
    for current in inventory_map.values():
        episode_nos = sorted(int(value) for value in set(current["episode_nos"]))
        distinct_episode_count = len(episode_nos)
        aliases = sorted(
            set(str(alias).strip() for alias in current["aliases"] if str(alias).strip()),
            key=lambda value: (0 if value == str(current["display_name"]) else 1, -len(value), value),
        )
        alias_stability = (
            "high"
            if len(aliases) <= 2 and distinct_episode_count >= 3
            else "medium"
            if distinct_episode_count >= 2
            else "low"
        )
        scene_centrality = (
            "high"
            if int(current["scene_weight_high_count"] or 0) >= max(2, distinct_episode_count // 2)
            else "medium"
            if int(current["scene_weight_high_count"] or 0) + int(current["scene_weight_medium_count"] or 0) >= 2
            else "low"
        )
        action_presence = "high" if int(current["summary_mention_count"] or 0) >= 4 and current["action_tag_counts"] else "medium" if current["action_tag_counts"] else "low"
        relation_presence = "high" if int(current["relation_episode_count"] or 0) >= 3 else "medium" if int(current["relation_episode_count"] or 0) >= 1 else "low"

        inventory_rows.append(
            {
                "character_key": str(current["character_key"]),
                "display_name": str(current["display_name"]),
                "aliases": aliases[:8],
                "entity_kind": str(current["entity_kind"]),
                "is_protagonist": bool(current["is_protagonist"]),
                "is_first_person": bool(current["is_first_person"]),
                "first_seen_episode_no": episode_nos[0] if episode_nos else 0,
                "latest_seen_episode_no": episode_nos[-1] if episode_nos else 0,
                "evidence_episode_nos": episode_nos[:120],
                "distinct_episode_count": distinct_episode_count,
                "summary_mention_count": int(current["summary_mention_count"] or 0),
                "voice_evidence_count": int(current["voice_evidence_count"] or 0),
                "relation_episode_count": int(current["relation_episode_count"] or 0),
                "scene_weight_counts": {
                    "high": int(current["scene_weight_high_count"] or 0),
                    "medium": int(current["scene_weight_medium_count"] or 0),
                    "low": int(current["scene_weight_low_count"] or 0),
                },
                "scene_centrality": scene_centrality,
                "alias_stability": alias_stability,
                "action_presence": action_presence,
                "relation_presence": relation_presence,
                "dominant_action_tags": [
                    key for key, _ in sorted(current["action_tag_counts"].items(), key=lambda item: (-item[1], item[0]))[:5]
                ],
                "dominant_affect_tags": [
                    key for key, _ in sorted(current["affect_tag_counts"].items(), key=lambda item: (-item[1], item[0]))[:5]
                ],
            }
        )
    return sorted(
        inventory_rows,
        key=lambda item: (
            0 if bool(item["is_protagonist"]) else 1,
            -int(item["distinct_episode_count"] or 0),
            -int(item["summary_mention_count"] or 0),
            str(item["display_name"]),
        ),
    )


def is_generic_character_label(value: str) -> bool:
    normalized = normalize_signal_entity_label(value)
    return not normalized or normalized in GENERIC_CHARACTER_LABELS


def build_character_inventory_v3_observations(signal_rows: list[dict]) -> list[dict[str, object]]:
    observations: list[dict[str, object]] = []
    for row in signal_rows:
        payload = extract_json_object(str(row.get("summary_text") or "")) or {}
        episode_no = int(payload.get("episode_no") or row.get("episode_from") or 0)
        source_hash = str(row.get("source_hash") or "").strip()
        summary_id = str(row.get("summary_id") or "").strip()
        episode_id = str(row.get("episode_id") or "").strip()
        observation_row_key = (
            f"summary:{summary_id}"
            if summary_id and summary_id != "0"
            else f"episode:{episode_id}"
            if episode_id and episode_id != "0"
            else f"episode_no:{episode_no}:hash:{source_hash[:16]}"
        )
        for item_index, item in enumerate(list(payload.get("mentioned_characters") or [])):
            if not isinstance(item, dict):
                continue
            entity_kind = str(item.get("entity_kind") or "person").strip().lower()
            if entity_kind not in {"person", "stable_role"}:
                continue
            source_character_key = str(item.get("character_key") or "").strip()
            display_name = str(item.get("display_name") or "").strip()
            if not source_character_key or not display_name:
                continue
            aliases = [
                str(alias).strip()
                for alias in list(item.get("aliases") or [])
                if str(alias).strip()
            ][:6]
            labels = []
            for label in [display_name, *aliases]:
                normalized_label = normalize_signal_entity_label(label)
                if normalized_label and normalized_label not in labels:
                    labels.append(normalized_label)
            non_generic_labels = [
                label
                for label in labels
                if label not in GENERIC_CHARACTER_LABELS
            ]
            narration_names = normalize_signal_name_list(item.get("narration_names"), limit=4)
            social_call_names = normalize_signal_name_list(item.get("social_call_names"), limit=4)
            persona_names = normalize_signal_name_list(item.get("persona_names"), limit=4)
            real_names = normalize_signal_name_list(item.get("real_names"), limit=4)
            scene_weight = str(item.get("scene_weight") or "low").strip().lower()
            if scene_weight not in {"high", "medium", "low"}:
                scene_weight = "low"
            role_in_episode = str(item.get("role_in_episode") or "support").strip().lower()
            if role_in_episode not in {"lead", "counterpart", "support", "obstacle"}:
                role_in_episode = "support"
            voice_mode = str(item.get("voice_mode") or "narration_only").strip().lower()
            if voice_mode not in {"dialogue", "monologue", "narration_only"}:
                voice_mode = "narration_only"
            relation_edges = []
            for edge in list(item.get("relation_edges") or []):
                if not isinstance(edge, dict):
                    continue
                target_key = str(edge.get("target_key") or "").strip()
                target_label = str(edge.get("target_label") or "").strip()
                if not target_key and not target_label:
                    continue
                relation_edges.append(
                    {
                        "target_key": target_key,
                        "target_label": target_label,
                        "normalized_target_label": normalize_signal_entity_label(target_label),
                        "relation_tag": str(edge.get("relation_tag") or "").strip()[:20],
                    }
                )
            identity_claims = []
            for claim in list(item.get("identity_claims") or []):
                if not isinstance(claim, dict):
                    continue
                target_key = str(claim.get("target_key") or "").strip()
                target_label = str(claim.get("target_label") or "").strip()
                normalized_target_label = normalize_signal_entity_label(
                    str(claim.get("normalized_target_label") or target_label)
                )
                claim_type = str(claim.get("claim_type") or "").strip().lower()
                if claim_type not in IDENTITY_CLAIM_TYPES:
                    continue
                if not target_key and not normalized_target_label:
                    continue
                if normalized_target_label in GENERIC_CHARACTER_LABELS:
                    continue
                identity_claims.append(
                    {
                        "target_key": target_key,
                        "target_label": target_label,
                        "normalized_target_label": normalized_target_label,
                        "claim_type": claim_type,
                        "evidence": str(claim.get("evidence") or "").strip()[:80],
                    }
                )
                if claim_type in SOCIAL_PERSONA_IDENTITY_CLAIM_TYPES:
                    persona_names = append_unique_name_signal(persona_names, target_label, limit=4)
                elif claim_type in REAL_NAME_IDENTITY_CLAIM_TYPES:
                    real_names = append_unique_name_signal(real_names, target_label, limit=4)
            observations.append(
                {
                    "observation_id": f"{observation_row_key}:{item_index}",
                    "summary_id": summary_id,
                    "source_hash": source_hash,
                    "episode_no": episode_no,
                    "source_character_key": source_character_key,
                    "display_name": display_name,
                    "aliases": aliases,
                    "narration_names": narration_names,
                    "social_call_names": social_call_names,
                    "persona_names": persona_names,
                    "real_names": real_names,
                    "normalized_labels": labels,
                    "non_generic_labels": non_generic_labels,
                    "primary_non_generic_label": non_generic_labels[0] if non_generic_labels else "",
                    "is_generic_display_name": is_generic_character_label(display_name),
                    "entity_kind": entity_kind,
                    "work_protagonist": parse_yes_no_flag(item.get("is_work_protagonist"), default=parse_yes_no_flag(item.get("is_protagonist"))),
                    "episode_focal": parse_yes_no_flag(item.get("is_episode_focal"), default=parse_yes_no_flag(item.get("is_protagonist"))),
                    "first_person": parse_yes_no_flag(item.get("is_first_person")),
                    "scene_weight": scene_weight,
                    "role_in_episode": role_in_episode,
                    "voice_mode": voice_mode,
                    "action_tags": [
                        str(tag).strip()[:20]
                        for tag in list(item.get("action_tags") or [])
                        if str(tag).strip()
                    ][:4],
                    "affect_tags": [
                        str(tag).strip()[:20]
                        for tag in list(item.get("affect_tags") or [])
                        if str(tag).strip()
                    ][:4],
                    "relation_edges": relation_edges[:5],
                    "identity_claims": identity_claims[:4],
                }
            )
    return observations


def _find_union_parent(parents: list[int], index: int) -> int:
    while parents[index] != index:
        parents[index] = parents[parents[index]]
        index = parents[index]
    return index


def _build_cannot_link_parent_index(
    parents: list[int],
    cannot_link_pairs: set[tuple[int, int]],
) -> dict[int, set[int]]:
    cannot_link_parent_index: dict[int, set[int]] = {}
    for cannot_left, cannot_right in cannot_link_pairs:
        cannot_left_parent = _find_union_parent(parents, cannot_left)
        cannot_right_parent = _find_union_parent(parents, cannot_right)
        if cannot_left_parent == cannot_right_parent:
            continue
        cannot_link_parent_index.setdefault(cannot_left_parent, set()).add(cannot_right_parent)
        cannot_link_parent_index.setdefault(cannot_right_parent, set()).add(cannot_left_parent)
    return cannot_link_parent_index


def _merge_cannot_link_parent_index(
    cannot_link_parent_index: dict[int, set[int]],
    *,
    keep_parent: int,
    remove_parent: int,
) -> None:
    keep_neighbors = set(cannot_link_parent_index.get(keep_parent) or set())
    remove_neighbors = set(cannot_link_parent_index.get(remove_parent) or set())
    old_neighbors = keep_neighbors | remove_neighbors
    merged_neighbors = old_neighbors - {keep_parent, remove_parent}

    for neighbor in old_neighbors:
        if neighbor in {keep_parent, remove_parent}:
            continue
        neighbor_links = cannot_link_parent_index.setdefault(neighbor, set())
        neighbor_links.discard(keep_parent)
        neighbor_links.discard(remove_parent)
        neighbor_links.add(keep_parent)

    if merged_neighbors:
        cannot_link_parent_index[keep_parent] = merged_neighbors
    else:
        cannot_link_parent_index.pop(keep_parent, None)
    cannot_link_parent_index.pop(remove_parent, None)


def _union_observations_with_cannot_link_indexes(
    parents: list[int],
    left: int,
    right: int,
    cannot_link_parent_indexes: list[dict[int, set[int]]],
) -> None:
    left_parent = _find_union_parent(parents, left)
    right_parent = _find_union_parent(parents, right)
    if left_parent == right_parent:
        return
    parents[right_parent] = left_parent
    for cannot_link_parent_index in cannot_link_parent_indexes:
        _merge_cannot_link_parent_index(
            cannot_link_parent_index,
            keep_parent=left_parent,
            remove_parent=right_parent,
        )


def _is_generic_protagonist_source_key(source_key: str) -> bool:
    text = str(source_key or "").strip().lower()
    return text in {"protagonist:first_person", "protagonist:generic"} or text.startswith("protagonist:generic:")


def _generic_source_key_observations_can_union(
    left: dict[str, object],
    right: dict[str, object],
) -> bool:
    left_labels = {str(label) for label in list(left.get("non_generic_labels") or []) if str(label)}
    right_labels = {str(label) for label in list(right.get("non_generic_labels") or []) if str(label)}
    if not left_labels or not right_labels:
        return False
    if left_labels & right_labels:
        return True
    return any(
        _labels_are_same_character_name_variant(left_label, right_label)
        or _labels_are_contextual_call_variant(left_label, right_label)
        for left_label in left_labels
        for right_label in right_labels
    )


def _would_merge_cannot_link_pair(
    parents: list[int],
    left: int,
    right: int,
    cannot_link_parent_index: dict[int, set[int]],
) -> bool:
    left_parent = _find_union_parent(parents, left)
    right_parent = _find_union_parent(parents, right)
    if left_parent == right_parent:
        return False
    return right_parent in cannot_link_parent_index.get(left_parent, set())


def _labels_are_same_character_name_variant(left: str, right: str) -> bool:
    left_label = normalize_signal_entity_label(left)
    right_label = normalize_signal_entity_label(right)
    if (
        not left_label
        or not right_label
        or left_label == right_label
        or left_label in GENERIC_CHARACTER_LABELS
        or right_label in GENERIC_CHARACTER_LABELS
    ):
        return False
    short_label, long_label = sorted([left_label, right_label], key=len)
    if len(short_label) < 2:
        return False
    return long_label.startswith(short_label) or long_label.endswith(short_label)


def _strip_contextual_call_suffix(label: str) -> str:
    normalized_label = normalize_signal_entity_label(label)
    if len(normalized_label) <= 2:
        return ""
    for suffix in ("씨", "이"):
        if not normalized_label.endswith(suffix):
            continue
        base_label = normalized_label[: -len(suffix)]
        if len(base_label) >= 2 and base_label not in GENERIC_CHARACTER_LABELS:
            return base_label
    return ""


def _labels_are_contextual_call_variant(left: str, right: str) -> bool:
    left_label = normalize_signal_entity_label(left)
    right_label = normalize_signal_entity_label(right)
    if not left_label or not right_label or left_label == right_label:
        return False
    return _strip_contextual_call_suffix(left_label) == right_label or _strip_contextual_call_suffix(right_label) == left_label


def _build_same_character_name_variant_observation_pairs(
    observation_label_sets: list[set[str]],
    focal_indexes: list[int],
) -> list[tuple[int, int]]:
    label_to_focal_indexes: dict[str, list[int]] = {}
    for index in focal_indexes:
        for label in observation_label_sets[index]:
            label_to_focal_indexes.setdefault(label, []).append(index)

    observation_pairs: set[tuple[int, int]] = set()
    labels = sorted(label_to_focal_indexes)
    for left_position, left_label in enumerate(labels):
        for right_label in labels[left_position + 1:]:
            if not _labels_are_same_character_name_variant(left_label, right_label):
                continue
            for left_index in label_to_focal_indexes[left_label]:
                for right_index in label_to_focal_indexes[right_label]:
                    if left_index == right_index:
                        continue
                    observation_pairs.add(tuple(sorted((left_index, right_index))))
    return sorted(observation_pairs)


def _identity_claim_labels_are_name_variant(
    source_label: str,
    target_label: str,
    source_labels: list[str],
) -> bool:
    if _labels_are_same_character_name_variant(source_label, target_label):
        return True
    left_label = normalize_signal_entity_label(source_label)
    right_label = normalize_signal_entity_label(target_label)
    if not left_label or not right_label or left_label == right_label:
        return False
    short_label, long_label = sorted([left_label, right_label], key=len)
    if len(short_label) != 1:
        return False
    source_label_set = {normalize_signal_entity_label(label) for label in source_labels if str(label)}
    return (
        short_label in source_label_set
        and long_label in source_label_set
        and (long_label.startswith(short_label) or long_label.endswith(short_label))
    )


def _build_identity_bridge_observation_pairs(
    bridge_label_pairs: set[tuple[str, str]],
    label_to_indexes: dict[str, list[int]],
) -> list[tuple[int, int]]:
    observation_pairs: set[tuple[int, int]] = set()
    for left_label, right_label in bridge_label_pairs:
        for left_index in label_to_indexes.get(left_label, []):
            for right_index in label_to_indexes.get(right_label, []):
                if left_index == right_index:
                    continue
                observation_pairs.add(tuple(sorted((left_index, right_index))))
    return sorted(observation_pairs)


def _add_identity_bridge_label_pair(
    bridge_label_pairs: set[tuple[str, str]],
    left_label: str,
    right_label: str,
) -> None:
    left = normalize_signal_entity_label(left_label)
    right = normalize_signal_entity_label(right_label)
    if (
        not left
        or not right
        or left == right
        or left in GENERIC_CHARACTER_LABELS
        or right in GENERIC_CHARACTER_LABELS
    ):
        return
    bridge_label_pairs.add(tuple(sorted((left, right))))


def _identity_claim_label_is_blocked(label: str) -> bool:
    normalized = normalize_signal_entity_label(label)
    if not normalized or normalized in GENERIC_CHARACTER_LABELS:
        return True
    if _identity_claim_label_has_possessive_block_phrase(normalized):
        return True
    if _identity_claim_label_has_group_suffix(normalized):
        return True
    if _identity_claim_label_has_ordinal_title_phrase(normalized):
        return True
    if _identity_claim_label_has_descriptor_phrase(normalized):
        return True
    return _identity_claim_label_has_block_token(normalized)


def _identity_claim_label_has_possessive_block_phrase(normalized: str) -> bool:
    match = re.search(r"의\s*(?P<tail>.+)$", normalized)
    if not match:
        return False
    tail = match.group("tail").strip()
    return tail in GENERIC_CHARACTER_LABELS or _identity_claim_label_has_block_token(tail)


def _identity_claim_label_has_block_token(normalized: str) -> bool:
    if not normalized:
        return False
    words = [word for word in re.split(r"\s+", normalized) if word]
    if any(word in IDENTITY_LABEL_BLOCK_WORD_TOKENS for word in words):
        return True
    return any(
        len(normalized) > len(token) and normalized.endswith(token)
        for token in IDENTITY_LABEL_BLOCK_SUFFIX_TOKENS
    )


def _identity_claim_label_has_group_suffix(normalized: str) -> bool:
    return any(
        normalized == token or (len(normalized) > len(token) and normalized.endswith(token))
        for token in IDENTITY_LABEL_BLOCK_GROUP_SUFFIX_TOKENS
    )


def _identity_claim_label_has_ordinal_title_phrase(normalized: str) -> bool:
    for token in IDENTITY_LABEL_BLOCK_ORDINAL_TITLE_SUFFIX_TOKENS:
        if len(normalized) <= len(token) or not normalized.endswith(token):
            continue
        prefix = normalized[: -len(token)]
        if prefix.startswith("제") and len(prefix) > 1:
            prefix = prefix[1:]
        if re.fullmatch(r"(?:[0-9]+|[일이삼사오육칠팔구십]+|첫|둘째|셋째|넷째|다섯째|여섯째|일곱째|여덟째|아홉째|열째)", prefix):
            return True
    return False


def _identity_claim_label_has_descriptor_phrase(normalized: str) -> bool:
    return any(pattern.fullmatch(normalized) for pattern in IDENTITY_LABEL_BLOCK_DESCRIPTOR_PATTERNS)


def _display_label_has_generic_parenthetical_block(normalized: str) -> bool:
    match = re.fullmatch(r"(?P<prefix>[^()]+)\((?P<inner>[^()]+)\)", normalized)
    if not match:
        return False
    prefix = normalize_signal_entity_label(match.group("prefix"))
    inner = normalize_signal_entity_label(match.group("inner"))
    if not prefix or not inner:
        return False
    prefix_generic = prefix in NON_PERSONA_GENERIC_LABELS or _identity_claim_label_has_block_token(prefix)
    inner_generic = inner in NON_PERSONA_GENERIC_LABELS or _identity_claim_label_has_block_token(inner)
    return prefix_generic and inner_generic


def _display_label_has_leading_particle_honorific_phrase(label: str) -> bool:
    match = re.fullmatch(
        r"(?:은|는|이|가|을|를|도|만)\s+(?P<title>[가-힣A-Za-z0-9 ]{1,12})",
        str(label or "").strip(),
    )
    if not match:
        return False
    return _is_honorific_address_term(match.group("title"))


def _display_label_has_hard_public_block(label: str) -> bool:
    if _display_label_has_leading_particle_honorific_phrase(label):
        return True
    normalized = normalize_signal_entity_label(label)
    if not normalized or normalized in NON_PERSONA_GENERIC_LABELS:
        return True
    if _display_label_has_generic_parenthetical_block(normalized):
        return True
    if _identity_claim_label_has_possessive_block_phrase(normalized):
        return True
    if _identity_claim_label_has_group_suffix(normalized):
        return True
    if _identity_claim_label_has_ordinal_title_phrase(normalized):
        return True
    return _identity_claim_label_has_descriptor_phrase(normalized)


def _is_role_like_persona_label_candidate(label: str) -> bool:
    normalized = normalize_signal_entity_label(label)
    if _display_label_has_hard_public_block(normalized):
        return False
    return normalized in GENERIC_CHARACTER_LABELS or _identity_claim_label_has_block_token(normalized)


def _inventory_identity_blocking_conflict_reasons(row: dict[str, object]) -> list[str]:
    return [
        str(reason)
        for reason in list(row.get("identity_conflict_reasons") or [])
        if str(reason) not in NON_BLOCKING_INVENTORY_IDENTITY_CONFLICT_REASONS
    ]


def _inventory_identity_is_public_resolved(row: dict[str, object]) -> bool:
    identity_status = str(row.get("identity_status") or "")
    if identity_status == "RESOLVED_NAMED":
        return not _inventory_identity_blocking_conflict_reasons(row)
    if identity_status == "CONFLICT":
        return not _inventory_identity_blocking_conflict_reasons(row)
    return False


def _inventory_row_uses_only_generic_first_person_source(row: dict[str, object]) -> bool:
    source_keys = [
        str(source_key or "").strip()
        for source_key in list(row.get("source_character_keys") or [])
        if str(source_key or "").strip()
    ]
    if not source_keys:
        return False
    first_person_count = int(dict(row.get("first_person_evidence") or {}).get("episode_count") or 0)
    return first_person_count > 0 and all(_is_generic_protagonist_source_key(source_key) for source_key in source_keys)


def _inventory_row_has_positive_name_signal(row: dict[str, object]) -> bool:
    display_label = normalize_signal_entity_label(str(row.get("display_name") or ""))
    if (
        not display_label
        or display_label in GENERIC_CHARACTER_LABELS
        or _identity_claim_label_is_blocked(display_label)
        or _display_label_has_hard_public_block(display_label)
    ):
        return False

    source_keys = [
        str(source_key or "").strip()
        for source_key in list(row.get("source_character_keys") or [])
        if str(source_key or "").strip()
    ]
    if any(not _is_generic_protagonist_source_key(source_key) for source_key in source_keys):
        return True

    name_signal_labels = {
        normalize_signal_entity_label(str(label or ""))
        for field in ("narration_names", "social_call_names", "persona_names", "real_names")
        for label in list(row.get(field) or [])
        if normalize_signal_entity_label(str(label or ""))
    }
    return any(
        display_label == label
        or _labels_are_same_character_name_variant(display_label, label)
        or _labels_are_contextual_call_variant(display_label, label)
        for label in name_signal_labels
    )


def _mark_unverified_first_person_identity_rows(rows: list[dict[str, object]]) -> None:
    for row in rows:
        if str(row.get("identity_status") or "") != "RESOLVED_NAMED":
            continue
        if not _inventory_row_uses_only_generic_first_person_source(row):
            continue
        if _inventory_row_has_positive_name_signal(row):
            continue
        row["identity_status"] = "UNRESOLVED"
        row["identity_confidence"] = "low"
        row["identity_conflict_reasons"] = sorted(
            set(list(row.get("identity_conflict_reasons") or []) + ["first_person_identity_unverified"])
        )


def _has_strong_role_like_persona_evidence(row: dict[str, object]) -> bool:
    display_name = str(row.get("display_name") or "").strip()
    if not _is_role_like_persona_label_candidate(display_name):
        return False
    if _inventory_identity_blocking_conflict_reasons(row):
        return False

    distinct_episode_count = int(row.get("distinct_episode_count") or 0)
    if distinct_episode_count < 3:
        return False

    voice_counts = dict(row.get("voice_mode_counts") or {})
    speaking_episode_count = int(voice_counts.get("dialogue") or 0) + int(voice_counts.get("monologue") or 0)
    if speaking_episode_count < 2:
        return False

    role_counts = dict(row.get("episode_role_counts") or {})
    work_protagonist_count = int(dict(row.get("work_protagonist_evidence") or {}).get("episode_count") or 0)
    focal_count = int(dict(row.get("episode_focal_evidence") or {}).get("episode_count") or 0)
    lead_count = int(role_counts.get("lead") or 0)
    relation_episode_count = int(row.get("relation_episode_count") or 0)

    if work_protagonist_count >= 2 and focal_count >= 2:
        return True
    return focal_count >= 3 and lead_count >= 3 and (distinct_episode_count >= 5 or relation_episode_count >= 2)


def _is_identity_transfer_relation_tag(value: str) -> bool:
    normalized = normalize_signal_entity_label(value)
    return bool(normalized and any(token in normalized for token in IDENTITY_TRANSFER_RELATION_TAG_TOKENS))


def _is_protagonist_like_identity_source(observation: dict[str, object]) -> bool:
    source_key = str(observation.get("source_character_key") or "")
    return (
        source_key.startswith("protagonist:")
        or bool(observation.get("work_protagonist"))
        or bool(observation.get("first_person"))
        or (
            bool(observation.get("episode_focal"))
            and str(observation.get("role_in_episode") or "") == "lead"
        )
    )


def _is_generic_protagonist_identity_source(observation: dict[str, object]) -> bool:
    if not _is_protagonist_like_identity_source(observation):
        return False
    display_label = normalize_signal_entity_label(str(observation.get("display_name") or ""))
    return display_label in GENERIC_PROTAGONIST_IDENTITY_SOURCE_LABELS


def _transfer_identity_target_label(observation: dict[str, object]) -> str:
    primary_label = str(observation.get("primary_non_generic_label") or "")
    if primary_label and not _identity_claim_label_is_blocked(primary_label):
        return primary_label
    display_label = normalize_signal_entity_label(str(observation.get("display_name") or ""))
    if display_label and _is_role_like_persona_label_candidate(display_label):
        return display_label
    return ""


def _observation_target_match_labels(observation: dict[str, object]) -> set[str]:
    labels = {
        normalize_signal_entity_label(str(observation.get("display_name") or "")),
        *[
            normalize_signal_entity_label(str(label or ""))
            for label in list(observation.get("normalized_labels") or [])
        ],
    }
    return {label for label in labels if label}


def _relation_edge_targets_observation(edge: dict[str, object], target: dict[str, object]) -> bool:
    target_key = str(edge.get("target_key") or "").strip()
    if target_key and target_key == str(target.get("source_character_key") or ""):
        return True
    target_label = normalize_signal_entity_label(str(edge.get("normalized_target_label") or edge.get("target_label") or ""))
    return bool(target_label and target_label in _observation_target_match_labels(target))


def _observation_has_identity_transfer_relation_to(
    source: dict[str, object],
    target: dict[str, object],
) -> bool:
    for edge in list(source.get("relation_edges") or []):
        if not isinstance(edge, dict) or not _is_identity_transfer_relation_tag(str(edge.get("relation_tag") or "")):
            continue
        if _relation_edge_targets_observation(edge, target):
            return True
    return False


def _observations_have_independent_voice_conflict(left: dict[str, object], right: dict[str, object]) -> bool:
    left_episode = int(left.get("episode_no") or 0)
    if left_episode <= 0 or left_episode != int(right.get("episode_no") or 0):
        return False
    speaking_modes = {"dialogue", "monologue"}
    if str(left.get("voice_mode") or "") not in speaking_modes or str(right.get("voice_mode") or "") not in speaking_modes:
        return False
    left_label = normalize_signal_entity_label(str(left.get("display_name") or ""))
    right_label = normalize_signal_entity_label(str(right.get("display_name") or ""))
    return bool(left_label and right_label and left_label != right_label)


def _collect_transfer_identity_bridge_pairs(
    observations: list[dict[str, object]],
    *,
    source_key_to_indexes: dict[str, list[int]],
    label_to_indexes: dict[str, list[int]],
    persona_label_to_indexes: dict[str, list[int]],
) -> set[tuple[int, int]]:
    bridge_pairs: set[tuple[int, int]] = set()

    def target_indexes_for(target_key: str, target_label: str) -> set[int]:
        indexes = set(source_key_to_indexes.get(str(target_key or ""), []))
        normalized_label = normalize_signal_entity_label(target_label)
        if normalized_label:
            indexes.update(label_to_indexes.get(normalized_label, []))
            indexes.update(persona_label_to_indexes.get(normalized_label, []))
        return indexes

    def add_bridge_pair(left_index: int, right_index: int, *, require_generic_source: bool) -> None:
        if left_index == right_index:
            return
        left = observations[left_index]
        right = observations[right_index]
        left_source = (
            _is_generic_protagonist_identity_source(left)
            if require_generic_source
            else _is_protagonist_like_identity_source(left)
        )
        right_source = (
            _is_generic_protagonist_identity_source(right)
            if require_generic_source
            else _is_protagonist_like_identity_source(right)
        )
        left_target_label = _transfer_identity_target_label(left)
        right_target_label = _transfer_identity_target_label(right)
        if not ((left_source and right_target_label) or (right_source and left_target_label)):
            return
        if _observations_have_independent_voice_conflict(left, right):
            return
        bridge_pairs.add(tuple(sorted((left_index, right_index))))

    for source_index, observation in enumerate(observations):
        for claim in list(observation.get("identity_claims") or []):
            if not isinstance(claim, dict):
                continue
            claim_type = str(claim.get("claim_type") or "").strip().lower()
            if claim_type not in TRANSFER_IDENTITY_CLAIM_TYPES:
                continue
            for target_index in target_indexes_for(
                str(claim.get("target_key") or ""),
                str(claim.get("normalized_target_label") or claim.get("target_label") or ""),
            ):
                add_bridge_pair(source_index, target_index, require_generic_source=False)

        for edge in list(observation.get("relation_edges") or []):
            if not isinstance(edge, dict) or not _is_identity_transfer_relation_tag(str(edge.get("relation_tag") or "")):
                continue
            target_indexes = target_indexes_for(
                str(edge.get("target_key") or ""),
                str(edge.get("normalized_target_label") or edge.get("target_label") or ""),
            )
            has_reciprocal_identity_transfer = any(
                _observation_has_identity_transfer_relation_to(observations[target_index], observation)
                for target_index in target_indexes
            )
            if not has_reciprocal_identity_transfer:
                continue
            for target_index in target_indexes:
                add_bridge_pair(source_index, target_index, require_generic_source=True)

    return bridge_pairs


def _collect_cluster_name_signal_counts(
    observations: list[dict[str, object]],
    field_names: tuple[str, ...],
) -> tuple[Counter[str], dict[str, str]]:
    counts: Counter[str] = Counter()
    raw_by_normalized: dict[str, str] = {}
    for observation in observations:
        episode_no = int(observation.get("episode_no") or 0)
        seen_in_episode: set[str] = set()
        for field_name in field_names:
            for value in list(observation.get(field_name) or []):
                raw_label = str(value or "").strip()
                normalized_label = normalize_signal_entity_label(raw_label)
                if (
                    not raw_label
                    or not normalized_label
                    or normalized_label in GENERIC_CHARACTER_LABELS
                    or _identity_claim_label_is_blocked(raw_label)
                ):
                    continue
                signal_key = f"{episode_no}:{normalized_label}" if episode_no > 0 else normalized_label
                if signal_key in seen_in_episode:
                    continue
                seen_in_episode.add(signal_key)
                counts[normalized_label] += 1
                raw_by_normalized.setdefault(normalized_label, raw_label[:40])
    return counts, raw_by_normalized


def _choose_cluster_social_display_name(
    observations: list[dict[str, object]],
    *,
    identity_label: str,
) -> tuple[str, str]:
    social_counts, social_raw = _collect_cluster_name_signal_counts(observations, ("social_call_names",))
    persona_counts, persona_raw = _collect_cluster_name_signal_counts(observations, ("persona_names",))
    real_counts, _ = _collect_cluster_name_signal_counts(observations, ("real_names",))
    narration_counts, _ = _collect_cluster_name_signal_counts(observations, ("narration_names",))
    social_identity_claim_labels = _collect_cluster_social_identity_claim_labels(observations)
    candidates: list[tuple[int, int, int, str, str, str]] = []
    normalized_identity_label = normalize_signal_entity_label(identity_label)
    for normalized_label, count in social_counts.items():
        raw_label = social_raw[normalized_label]
        is_identity_label = bool(normalized_identity_label and normalized_label == normalized_identity_label)
        if not is_identity_label and count < 2:
            continue
        if not is_identity_label and _social_display_label_is_contextual(raw_label):
            continue
        if not is_identity_label and not _social_display_label_is_identity_backed(
            normalized_label,
            identity_label=normalized_identity_label,
            social_identity_claim_labels=social_identity_claim_labels,
            real_counts=real_counts,
            narration_counts=narration_counts,
            persona_counts=persona_counts,
        ):
            continue
        candidates.append((0, -count, -len(normalized_label), normalized_label, raw_label, "social_call_names"))
    for normalized_label, count in persona_counts.items():
        is_identity_label = bool(normalized_identity_label and normalized_label == normalized_identity_label)
        if not is_identity_label and not _social_display_label_is_identity_backed(
            normalized_label,
            identity_label=normalized_identity_label,
            social_identity_claim_labels=social_identity_claim_labels,
            real_counts=real_counts,
            narration_counts=narration_counts,
            persona_counts=persona_counts,
        ):
            continue
        candidates.append((1, -count, -len(normalized_label), normalized_label, persona_raw[normalized_label], "persona_names"))
    if not candidates:
        return "", ""
    _, _, _, normalized_label, raw_label, source = sorted(candidates)[0]
    if normalized_identity_label and normalized_label == normalized_identity_label:
        return raw_label, source
    return raw_label, source


def _collect_cluster_social_identity_claim_labels(observations: list[dict[str, object]]) -> set[str]:
    labels: set[str] = set()
    for observation in observations:
        for claim in list(observation.get("identity_claims") or []):
            if not isinstance(claim, dict):
                continue
            claim_type = str(claim.get("claim_type") or "").strip().lower()
            if claim_type not in SOCIAL_PERSONA_IDENTITY_CLAIM_TYPES:
                continue
            normalized_target_label = normalize_signal_entity_label(
                str(claim.get("normalized_target_label") or claim.get("target_label") or "")
            )
            if normalized_target_label and not _identity_claim_label_is_blocked(normalized_target_label):
                labels.add(normalized_target_label)
    return labels


def _social_display_label_is_identity_backed(
    normalized_label: str,
    *,
    identity_label: str,
    social_identity_claim_labels: set[str],
    real_counts: Counter[str],
    narration_counts: Counter[str],
    persona_counts: Counter[str],
) -> bool:
    if not normalized_label or _identity_claim_label_is_blocked(normalized_label):
        return False
    if normalized_label in social_identity_claim_labels:
        return True
    if normalized_label in real_counts:
        return True
    if identity_label and _labels_are_same_character_name_variant(identity_label, normalized_label):
        return True
    return bool(
        identity_label
        and normalized_label in identity_label
        and (normalized_label in narration_counts or normalized_label in persona_counts)
    )


def _social_display_label_is_contextual(label: str) -> bool:
    raw_label = str(label or "").strip()
    normalized_label = normalize_signal_entity_label(raw_label)
    if not normalized_label:
        return True
    if any(token in normalized_label for token in SOCIAL_DISPLAY_BLOCK_SUBSTRINGS):
        return True
    return any(normalized_label.endswith(suffix) for suffix in SOCIAL_DISPLAY_BLOCK_SUFFIXES)


def _collect_observation_alias_bridge_pairs(observations: list[dict[str, object]]) -> set[tuple[str, str]]:
    bridge_episode_counts: dict[tuple[str, str], set[int]] = {}
    bridge_focus_counts: Counter[tuple[str, str]] = Counter()
    for observation in observations:
        primary_label = str(observation.get("primary_non_generic_label") or "")
        if not primary_label or _identity_claim_label_is_blocked(primary_label):
            continue
        episode_no = int(observation.get("episode_no") or 0)
        labels = [
            str(label)
            for label in list(observation.get("non_generic_labels") or [])[1:]
            if str(label)
        ]
        for label in labels:
            if label == primary_label or _identity_claim_label_is_blocked(label):
                continue
            pair = tuple(sorted((primary_label, label)))
            bridge_episode_counts.setdefault(pair, set()).add(episode_no)
            if bool(observation.get("work_protagonist")) or bool(observation.get("episode_focal")):
                bridge_focus_counts[pair] += 1
    return {
        pair
        for pair, episode_nos in bridge_episode_counts.items()
        if len({episode_no for episode_no in episode_nos if episode_no > 0}) >= 2
        and bridge_focus_counts.get(pair, 0) >= 2
    }


def _build_bridge_label_match_index(label_pairs: set[tuple[str, str]]) -> dict[str, set[str]]:
    match_index: dict[str, set[str]] = {}
    for left_label, right_label in label_pairs:
        match_index.setdefault(left_label, set()).update({left_label, right_label})
        match_index.setdefault(right_label, set()).update({left_label, right_label})
    return match_index


def _label_sets_match_bridge_index(
    left_labels: set[str],
    right_labels: set[str],
    bridge_label_match_index: dict[str, set[str]],
) -> bool:
    if len(left_labels) > len(right_labels):
        left_labels, right_labels = right_labels, left_labels
    return any(bool(bridge_label_match_index.get(label, set()) & right_labels) for label in left_labels)


def _collect_alias_bridge_persona_display_pairs(
    observations: list[dict[str, object]],
    alias_bridge_label_pairs: set[tuple[str, str]],
) -> set[tuple[str, str]]:
    candidate_labels = {label for pair in alias_bridge_label_pairs for label in pair}
    alias_focus_counts: Counter[str] = Counter()
    display_focus_counts: Counter[str] = Counter()
    for observation in observations:
        if not (bool(observation.get("work_protagonist")) or bool(observation.get("episode_focal"))):
            continue
        display_label = normalize_signal_entity_label(str(observation.get("display_name") or ""))
        if display_label in candidate_labels:
            display_focus_counts[display_label] += 1
        primary_label = str(observation.get("primary_non_generic_label") or "")
        alias_labels = {
            normalize_signal_entity_label(str(alias or ""))
            for alias in list(observation.get("aliases") or [])
            if normalize_signal_entity_label(str(alias or ""))
        }
        for alias_label in alias_labels:
            if alias_label in candidate_labels and alias_label != primary_label:
                alias_focus_counts[alias_label] += 1
    return {
        pair
        for pair in alias_bridge_label_pairs
        if any(
            alias_focus_counts[label] >= 2 and display_focus_counts[label] >= 1
            for label in pair
        )
    }


def _choose_cluster_alias_bridge_display_name(
    observations: list[dict[str, object]],
    *,
    identity_label: str,
    alias_bridge_label_pairs: set[tuple[str, str]],
) -> tuple[str, str]:
    normalized_identity_label = normalize_signal_entity_label(identity_label)
    if not normalized_identity_label:
        return "", ""
    cluster_labels = {
        str(label)
        for observation in observations
        for label in list(observation.get("non_generic_labels") or [])
        if str(label)
    }
    candidate_labels = {
        label
        for pair in alias_bridge_label_pairs
        if set(pair).issubset(cluster_labels)
        for label in pair
    }
    if not candidate_labels:
        return "", ""

    counts: Counter[str] = Counter()
    focus_counts: Counter[str] = Counter()
    alias_focus_counts: Counter[str] = Counter()
    display_focus_counts: Counter[str] = Counter()
    raw_by_label: dict[str, str] = {}
    for observation in observations:
        episode_no = int(observation.get("episode_no") or 0)
        is_focused = bool(observation.get("work_protagonist")) or bool(observation.get("episode_focal"))
        seen_in_episode: set[str] = set()
        display_label = normalize_signal_entity_label(str(observation.get("display_name") or ""))
        if display_label in candidate_labels and is_focused:
            display_focus_counts[display_label] += 1
        alias_labels = [
            normalize_signal_entity_label(str(alias or ""))
            for alias in list(observation.get("aliases") or [])
            if normalize_signal_entity_label(str(alias or ""))
        ]
        for alias_label in set(alias_labels):
            if alias_label in candidate_labels and is_focused and alias_label != str(observation.get("primary_non_generic_label") or ""):
                alias_focus_counts[alias_label] += 1
        for raw_label in [observation.get("display_name"), *list(observation.get("aliases") or [])]:
            normalized_label = normalize_signal_entity_label(str(raw_label or ""))
            if normalized_label not in candidate_labels:
                continue
            signal_key = f"{episode_no}:{normalized_label}" if episode_no > 0 else normalized_label
            if signal_key in seen_in_episode:
                continue
            seen_in_episode.add(signal_key)
            counts[normalized_label] += 1
            if is_focused:
                focus_counts[normalized_label] += 1
            raw_by_label.setdefault(normalized_label, str(raw_label or "").strip()[:40])
    candidates = [
        (
            -alias_focus_counts[label],
            -display_focus_counts[label],
            -focus_counts[label],
            -counts[label],
            -len(label),
            label,
            raw_by_label.get(label, label),
        )
        for label in candidate_labels
        if alias_focus_counts[label] >= 2
        and display_focus_counts[label] >= 1
        and counts[label] >= 2
        and focus_counts[label] >= 2
        and raw_by_label.get(label)
    ]
    if not candidates:
        return "", ""
    _, _, _, _, _, _, raw_label = sorted(candidates)[0]
    return raw_label, "alias_bridge"


def _cluster_label_episode_counts(observations: list[dict[str, object]]) -> Counter[str]:
    label_episodes: dict[str, set[int]] = {}
    for observation in observations:
        episode_no = int(observation.get("episode_no") or 0)
        for label in list(observation.get("non_generic_labels") or []):
            normalized_label = str(label or "")
            if normalized_label:
                label_episodes.setdefault(normalized_label, set()).add(episode_no)
    return Counter({label: len({episode_no for episode_no in episode_nos if episode_no > 0}) for label, episode_nos in label_episodes.items()})


def _cluster_display_label_counts(observations: list[dict[str, object]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for observation in observations:
        normalized_label = normalize_signal_entity_label(str(observation.get("display_name") or ""))
        if normalized_label:
            counts[normalized_label] += 1
    return counts


def _display_variant_has_contextual_suffix(longer_label: str, shorter_label: str) -> bool:
    if not longer_label.startswith(shorter_label) or len(longer_label) <= len(shorter_label):
        return False
    suffix = longer_label[len(shorter_label):]
    if not suffix:
        return False
    if suffix.startswith("("):
        return True
    if len(suffix) == 1 and re.fullmatch(r"[가-힣]", suffix):
        return True
    suffix_tokens = (
        GENERIC_CHARACTER_LABELS
        | IDENTITY_LABEL_BLOCK_WORD_TOKENS
        | IDENTITY_LABEL_BLOCK_SUFFIX_TOKENS
        | IDENTITY_LABEL_BLOCK_GROUP_SUFFIX_TOKENS
        | IDENTITY_LABEL_BLOCK_ORDINAL_TITLE_SUFFIX_TOKENS
        | SOCIAL_DISPLAY_BLOCK_SUFFIXES
    )
    return suffix in suffix_tokens


def _prefer_non_contextual_label_for_contextual_call_variant(
    label: str,
    labels: list[str],
    label_episode_counts: Counter[str],
    display_label_counts: Counter[str],
) -> str:
    base_label = _strip_contextual_call_suffix(label)
    if not base_label:
        return label
    candidates = [
        candidate
        for candidate in labels
        if candidate != label
        and candidate not in GENERIC_CHARACTER_LABELS
        and not _strip_contextual_call_suffix(candidate)
        and (candidate == base_label or _labels_are_same_character_name_variant(base_label, candidate))
    ]
    if not candidates:
        return label
    return sorted(
        candidates,
        key=lambda value: (
            0 if len(value) > len(base_label) else 1,
            -label_episode_counts[value],
            -display_label_counts[value],
            -len(value),
            value,
        ),
    )[0]


def _prefer_parenthetical_persona_label(
    label: str,
    labels: list[str],
) -> str:
    normalized_label = normalize_signal_entity_label(label)
    match = re.fullmatch(r"(?P<prefix>[^()]+)\((?P<inner>[^()]+)\)", normalized_label)
    if not match:
        return label
    prefix = normalize_signal_entity_label(match.group("prefix"))
    inner = normalize_signal_entity_label(match.group("inner"))
    if prefix not in GENERIC_CHARACTER_LABELS or not inner:
        return label
    if inner in labels and inner not in GENERIC_CHARACTER_LABELS and not _identity_claim_label_is_blocked(inner):
        return inner
    return label


def _prefer_frequent_base_label_for_contextual_display_variant(
    label: str,
    labels: list[str],
    label_episode_counts: Counter[str],
    display_label_counts: Counter[str],
) -> str:
    candidates = [
        candidate
        for candidate in labels
        if candidate != label
        and candidate not in GENERIC_CHARACTER_LABELS
        and label_episode_counts[candidate] > label_episode_counts[label]
        and _display_variant_has_contextual_suffix(label, candidate)
    ]
    if not candidates:
        return label
    return sorted(
        candidates,
        key=lambda value: (
            -label_episode_counts[value],
            -display_label_counts[value],
            -len(value),
            value,
        ),
    )[0]


def resolve_character_inventory_v3_clusters(observations: list[dict[str, object]]) -> list[dict[str, object]]:
    parents = list(range(len(observations)))
    same_episode_cannot_link_pairs: set[tuple[int, int]] = set()
    relation_cannot_link_pairs: set[tuple[int, int]] = set()
    alias_bridge_label_pairs = _collect_observation_alias_bridge_pairs(observations)
    alias_bridge_persona_display_pairs = _collect_alias_bridge_persona_display_pairs(observations, alias_bridge_label_pairs)
    alias_bridge_label_match_index = _build_bridge_label_match_index(alias_bridge_label_pairs)
    alias_bridge_persona_display_match_index = _build_bridge_label_match_index(alias_bridge_persona_display_pairs)
    source_key_to_indexes: dict[str, list[int]] = {}
    label_to_indexes: dict[str, list[int]] = {}
    primary_label_to_indexes: dict[str, list[int]] = {}
    persona_label_to_indexes: dict[str, list[int]] = {}
    episode_to_indexes: dict[int, list[int]] = {}
    observation_label_sets: list[set[str]] = []

    for index, observation in enumerate(observations):
        observation_label_sets.append(
            {str(label) for label in list(observation.get("non_generic_labels") or []) if str(label)}
        )
        episode_no = int(observation.get("episode_no") or 0)
        if episode_no > 0:
            episode_to_indexes.setdefault(episode_no, []).append(index)
        source_key = str(observation.get("source_character_key") or "")
        source_key_to_indexes.setdefault(source_key, []).append(index)
        primary_label = str(observation.get("primary_non_generic_label") or "")
        if primary_label:
            primary_label_to_indexes.setdefault(primary_label, []).append(index)
        persona_label = normalize_signal_entity_label(str(observation.get("display_name") or ""))
        if _is_role_like_persona_label_candidate(persona_label):
            persona_label_to_indexes.setdefault(persona_label, []).append(index)
        for label in list(observation.get("non_generic_labels") or []):
            label_to_indexes.setdefault(str(label), []).append(index)

    transfer_identity_bridge_pairs = _collect_transfer_identity_bridge_pairs(
        observations,
        source_key_to_indexes=source_key_to_indexes,
        label_to_indexes=label_to_indexes,
        persona_label_to_indexes=persona_label_to_indexes,
    )

    authoritative_identity_bridge_label_pairs: set[tuple[str, str]] = set()
    name_variant_identity_bridge_label_pairs: set[tuple[str, str]] = set()
    for source_index, observation in enumerate(observations):
        source_labels = [
            str(label)
            for label in list(observation.get("non_generic_labels") or [])
            if str(label)
        ]
        if not source_labels:
            continue
        for claim in list(observation.get("identity_claims") or []):
            if not isinstance(claim, dict):
                continue
            claim_type = str(claim.get("claim_type") or "").strip().lower()
            if claim_type not in AUTHORITATIVE_IDENTITY_CLAIM_TYPES and claim_type not in NAME_VARIANT_IDENTITY_CLAIM_TYPES:
                continue
            target_labels = []
            normalized_target_label = str(claim.get("normalized_target_label") or "")
            if normalized_target_label and not _identity_claim_label_is_blocked(normalized_target_label):
                target_labels.append(normalized_target_label)
            for target_index in source_key_to_indexes.get(str(claim.get("target_key") or ""), []):
                if target_index == source_index:
                    continue
                target_labels.extend(
                    str(label)
                    for label in list(observations[target_index].get("non_generic_labels") or [])
                    if str(label)
                )
            for target_index in label_to_indexes.get(normalized_target_label, []):
                if target_index == source_index:
                    continue
                target_labels.extend(
                    str(label)
                    for label in list(observations[target_index].get("non_generic_labels") or [])
                    if str(label)
                )
            for source_label in source_labels:
                for target_label in target_labels:
                    if _identity_claim_label_is_blocked(source_label) or _identity_claim_label_is_blocked(target_label):
                        continue
                    if claim_type in AUTHORITATIVE_IDENTITY_CLAIM_TYPES:
                        _add_identity_bridge_label_pair(
                            authoritative_identity_bridge_label_pairs,
                            source_label,
                            target_label,
                        )
                    elif _identity_claim_labels_are_name_variant(source_label, target_label, source_labels):
                        _add_identity_bridge_label_pair(
                            name_variant_identity_bridge_label_pairs,
                            source_label,
                            target_label,
                        )

    for episode_indexes in episode_to_indexes.values():
        for position, left_index in enumerate(episode_indexes):
            left = observations[left_index]
            left_label = str(left.get("primary_non_generic_label") or "")
            if not left_label:
                continue
            for right_index in episode_indexes[position + 1:]:
                right = observations[right_index]
                right_label = str(right.get("primary_non_generic_label") or "")
                if right_label and left_label != right_label:
                    if tuple(sorted((left_index, right_index))) in transfer_identity_bridge_pairs:
                        continue
                    if _label_sets_match_bridge_index(
                        observation_label_sets[left_index],
                        observation_label_sets[right_index],
                        alias_bridge_label_match_index,
                    ):
                        continue
                    same_episode_cannot_link_pairs.add((left_index, right_index))

    for source_index, observation in enumerate(observations):
        for edge in list(observation.get("relation_edges") or []):
            if not isinstance(edge, dict):
                continue
            for target_index in source_key_to_indexes.get(str(edge.get("target_key") or ""), []):
                if source_index != target_index:
                    if tuple(sorted((source_index, target_index))) in transfer_identity_bridge_pairs:
                        continue
                    if _label_sets_match_bridge_index(
                        observation_label_sets[source_index],
                        observation_label_sets[target_index],
                        alias_bridge_persona_display_match_index,
                    ):
                        continue
                    relation_cannot_link_pairs.add(tuple(sorted((source_index, target_index))))
            target_label = str(edge.get("normalized_target_label") or "")
            for target_index in label_to_indexes.get(target_label, []):
                if source_index != target_index:
                    if tuple(sorted((source_index, target_index))) in transfer_identity_bridge_pairs:
                        continue
                    if _label_sets_match_bridge_index(
                        observation_label_sets[source_index],
                        observation_label_sets[target_index],
                        alias_bridge_persona_display_match_index,
                    ):
                        continue
                    relation_cannot_link_pairs.add(tuple(sorted((source_index, target_index))))

    cannot_link_pairs = set(relation_cannot_link_pairs)
    for left_index, right_index in same_episode_cannot_link_pairs:
        cannot_link_pairs.add((left_index, right_index))
    cannot_link_parent_index = _build_cannot_link_parent_index(parents, cannot_link_pairs)
    relation_cannot_link_parent_index = _build_cannot_link_parent_index(parents, relation_cannot_link_pairs)
    cannot_link_parent_indexes = [cannot_link_parent_index, relation_cannot_link_parent_index]

    for indexes in source_key_to_indexes.values():
        base_index = indexes[0]
        for other_index in indexes[1:]:
            if (
                _is_generic_protagonist_source_key(str(observations[base_index].get("source_character_key") or ""))
                and not _generic_source_key_observations_can_union(
                    observations[base_index],
                    observations[other_index],
                )
            ):
                continue
            pair = tuple(sorted((base_index, other_index)))
            if pair in cannot_link_pairs or _would_merge_cannot_link_pair(parents, base_index, other_index, cannot_link_parent_index):
                continue
            _union_observations_with_cannot_link_indexes(parents, base_index, other_index, cannot_link_parent_indexes)

    for indexes in primary_label_to_indexes.values():
        base_index = indexes[0]
        for other_index in indexes[1:]:
            pair = tuple(sorted((base_index, other_index)))
            if pair in cannot_link_pairs or _would_merge_cannot_link_pair(parents, base_index, other_index, cannot_link_parent_index):
                continue
            _union_observations_with_cannot_link_indexes(parents, base_index, other_index, cannot_link_parent_indexes)

    for indexes in persona_label_to_indexes.values():
        base_index = indexes[0]
        for other_index in indexes[1:]:
            pair = tuple(sorted((base_index, other_index)))
            if pair in cannot_link_pairs or _would_merge_cannot_link_pair(parents, base_index, other_index, cannot_link_parent_index):
                continue
            _union_observations_with_cannot_link_indexes(parents, base_index, other_index, cannot_link_parent_indexes)

    for left_index, right_index in sorted(transfer_identity_bridge_pairs):
        if (
            (left_index, right_index) in cannot_link_pairs
            or _would_merge_cannot_link_pair(parents, left_index, right_index, cannot_link_parent_index)
        ):
            continue
        _union_observations_with_cannot_link_indexes(parents, left_index, right_index, cannot_link_parent_indexes)

    for label_pair in alias_bridge_label_pairs:
        indexes = sorted(
            {
                index
                for label in label_pair
                for index in label_to_indexes.get(label, [])
            }
        )
        if not indexes:
            continue
        base_index = indexes[0]
        for other_index in indexes[1:]:
            pair = tuple(sorted((base_index, other_index)))
            if pair in relation_cannot_link_pairs or _would_merge_cannot_link_pair(parents, base_index, other_index, relation_cannot_link_parent_index):
                continue
            _union_observations_with_cannot_link_indexes(parents, base_index, other_index, cannot_link_parent_indexes)

    identity_bridge_observation_pairs = _build_identity_bridge_observation_pairs(
        authoritative_identity_bridge_label_pairs | name_variant_identity_bridge_label_pairs,
        label_to_indexes,
    )
    for left_index, right_index in identity_bridge_observation_pairs:
        if (left_index, right_index) in cannot_link_pairs or _would_merge_cannot_link_pair(
            parents,
            left_index,
            right_index,
            cannot_link_parent_index,
        ):
            continue
        _union_observations_with_cannot_link_indexes(parents, left_index, right_index, cannot_link_parent_indexes)

    same_character_name_variant_observation_pairs = _build_same_character_name_variant_observation_pairs(
        observation_label_sets,
        [
            index
            for index, observation in enumerate(observations)
            if bool(observation.get("episode_focal"))
        ],
    )
    for left_index, right_index in same_character_name_variant_observation_pairs:
        if (left_index, right_index) in cannot_link_pairs or _would_merge_cannot_link_pair(
            parents,
            left_index,
            right_index,
            cannot_link_parent_index,
        ):
            continue
        _union_observations_with_cannot_link_indexes(parents, left_index, right_index, cannot_link_parent_indexes)

    clusters_by_parent: dict[int, list[dict[str, object]]] = {}
    for index, observation in enumerate(observations):
        clusters_by_parent.setdefault(_find_union_parent(parents, index), []).append(observation)

    clusters: list[dict[str, object]] = []
    for cluster_observations in clusters_by_parent.values():
        source_keys = sorted(
            {
                str(observation.get("source_character_key") or "")
                for observation in cluster_observations
                if str(observation.get("source_character_key") or "")
            }
        )
        labels = sorted(
            {
                str(label)
                for observation in cluster_observations
                for label in list(observation.get("non_generic_labels") or [])
                if str(label)
            },
            key=lambda value: (-sum(
                1
                for observation in cluster_observations
                if value in list(observation.get("non_generic_labels") or [])
            ), -len(value), value),
        )
        generic_first_person = any(
            bool(observation.get("first_person")) and not list(observation.get("non_generic_labels") or [])
            for observation in cluster_observations
        ) and not labels
        conflict_reasons = []
        if generic_first_person:
            conflict_reasons.append("unresolved_generic_first_person")
        cluster_observation_ids = {str(observation.get("observation_id") or "") for observation in cluster_observations}
        for left_index, right_index in cannot_link_pairs:
            left_observation_id = str(observations[left_index].get("observation_id") or "")
            right_observation_id = str(observations[right_index].get("observation_id") or "")
            if left_observation_id in cluster_observation_ids and right_observation_id in cluster_observation_ids:
                conflict_reasons.append("cannot_link_name_conflict")
                break
        entity_kinds = Counter(str(observation.get("entity_kind") or "person") for observation in cluster_observations)
        identity_status = "RESOLVED_NAMED" if labels else "UNRESOLVED"
        if entity_kinds.get("stable_role", 0) > entity_kinds.get("person", 0) and labels:
            identity_status = "RESOLVED_STABLE_ROLE"
        if conflict_reasons:
            identity_status = "CONFLICT" if "cannot_link_name_conflict" in conflict_reasons else identity_status
        display_name = ""
        display_name_source = "identity_label"
        identity_label = ""
        label_episode_counts = _cluster_label_episode_counts(cluster_observations)
        display_label_counts = _cluster_display_label_counts(cluster_observations)
        display_label_candidates = [
            normalize_signal_entity_label(str(observation.get("display_name") or ""))
            for observation in cluster_observations
            if normalize_signal_entity_label(str(observation.get("display_name") or ""))
            and not is_generic_character_label(str(observation.get("display_name") or ""))
        ]
        if labels:
            label = labels[0]
            longer_display_labels = [
                candidate
                for candidate in display_label_candidates
                if candidate in labels
                and candidate != label
                and len(candidate) > len(label)
                and _labels_are_same_character_name_variant(label, candidate)
            ]
            if longer_display_labels:
                label = sorted(
                    longer_display_labels,
                    key=lambda value: (
                        -label_episode_counts[value],
                        -display_label_counts[value],
                        -len(value),
                        value,
                    ),
                )[0]
            elif len(label) == 1:
                longer_display_labels = [
                    candidate
                    for candidate in display_label_candidates
                    if candidate in labels and len(candidate) > 1
                ]
                if longer_display_labels:
                    label = sorted(
                        longer_display_labels,
                        key=lambda value: (
                            -label_episode_counts[value],
                            -display_label_counts[value],
                            -len(value),
                            value,
                        ),
                    )[0]
            label = _prefer_non_contextual_label_for_contextual_call_variant(
                label,
                labels,
                label_episode_counts,
                display_label_counts,
            )
            label = _prefer_parenthetical_persona_label(label, labels)
            label = _prefer_frequent_base_label_for_contextual_display_variant(
                label,
                labels,
                label_episode_counts,
                display_label_counts,
            )
            identity_label = label
            identity_display_name = next(
                (
                    str(observation.get("display_name") or "").strip()
                    for observation in cluster_observations
                    if normalize_signal_entity_label(str(observation.get("display_name") or "")) == label
                    and not is_generic_character_label(str(observation.get("display_name") or ""))
                ),
                label,
            )
            social_display_name, social_source = _choose_cluster_social_display_name(
                cluster_observations,
                identity_label=identity_label,
            )
            alias_bridge_display_name, alias_bridge_source = _choose_cluster_alias_bridge_display_name(
                cluster_observations,
                identity_label=identity_label,
                alias_bridge_label_pairs=alias_bridge_label_pairs,
            )
            alias_bridge_label = normalize_signal_entity_label(alias_bridge_display_name)
            alias_bridge_is_contextual_call = bool(
                alias_bridge_label
                and _strip_contextual_call_suffix(alias_bridge_label)
                and identity_label
                and not _strip_contextual_call_suffix(identity_label)
            )
            if alias_bridge_display_name and not alias_bridge_is_contextual_call:
                display_name = alias_bridge_display_name
                display_name_source = alias_bridge_source
            elif social_display_name:
                display_name = social_display_name
                display_name_source = social_source
            else:
                display_name = identity_display_name
        else:
            display_name = str(cluster_observations[0].get("display_name") or "주인공").strip()
        display_label = normalize_signal_entity_label(display_name)
        seed = (
            identity_label
            if identity_label and identity_label not in GENERIC_CHARACTER_LABELS
            else display_label
            if display_label and display_label not in GENERIC_CHARACTER_LABELS
            else display_label
            if display_label and _is_role_like_persona_label_candidate(display_label)
            else labels[0]
            if labels
            else sha256_text(",".join(str(obs.get("observation_id")) for obs in cluster_observations))[:12]
        )
        clusters.append(
            {
                "canonical_character_key": f"character:{seed}",
                "display_name": display_name,
                "display_name_source": display_name_source,
                "source_character_keys": source_keys,
                "observations": cluster_observations,
                "identity_status": identity_status,
                "identity_conflict_reasons": sorted(set(conflict_reasons)),
            }
        )
    canonical_key_counts = Counter(str(cluster.get("canonical_character_key") or "") for cluster in clusters)
    for cluster in clusters:
        canonical_key = str(cluster.get("canonical_character_key") or "")
        if canonical_key_counts.get(canonical_key, 0) <= 1:
            continue
        observations = list(cluster.get("observations") or [])
        duplicate_suffix = sha256_text(
            ",".join(
                sorted(
                    str(observation.get("observation_id") or "")
                    for observation in observations
                    if str(observation.get("observation_id") or "")
                )
            )
        )[:8]
        cluster["canonical_character_key"] = f"{canonical_key}:dup:{duplicate_suffix}"
        cluster["identity_status"] = "CONFLICT"
        cluster["identity_conflict_reasons"] = sorted(
            set(list(cluster.get("identity_conflict_reasons") or []) + ["duplicate_canonical_key"])
        )
    return clusters


def _episode_count(observations: list[dict[str, object]], predicate=None) -> int:
    episode_nos = set()
    for observation in observations:
        if predicate and not predicate(observation):
            continue
        episode_no = int(observation.get("episode_no") or 0)
        if episode_no > 0:
            episode_nos.add(episode_no)
    return len(episode_nos)


def _classify_character_inventory_v3_rows(
    rows: list[dict[str, object]],
    total_signal_episodes: int,
    *,
    protagonist_resolution: dict | None = None,
    locked_protagonist_rows: list[dict[str, object]] | None = None,
) -> None:
    scored_rows = []
    total_episodes = max(total_signal_episodes, 1)
    for row in rows:
        distinct_episode_count = int(row.get("distinct_episode_count") or 0)
        work_protagonist_count = int(dict(row.get("work_protagonist_evidence") or {}).get("episode_count") or 0)
        focal_count = int(dict(row.get("episode_focal_evidence") or {}).get("episode_count") or 0)
        first_person_count = int(dict(row.get("first_person_evidence") or {}).get("episode_count") or 0)
        role_counts = dict(row.get("episode_role_counts") or {})
        scene_counts = dict(row.get("scene_weight_counts") or {})
        voice_counts = dict(row.get("voice_mode_counts") or {})
        lead_count = int(role_counts.get("lead") or 0)
        high_count = int(scene_counts.get("high") or 0)
        voice_count = int(voice_counts.get("dialogue") or 0) + int(voice_counts.get("monologue") or 0)
        coverage_score = min(distinct_episode_count / total_episodes, 1.0)
        continuity_score = 1.0 if distinct_episode_count >= 3 else 0.5 if distinct_episode_count >= 2 else 0.0
        score = (
            0.50 * min(work_protagonist_count / total_episodes, 1.0)
            + 0.10 * min(lead_count / total_episodes, 1.0)
            + 0.15 * min(first_person_count / total_episodes, 1.0)
            + 0.10 * coverage_score
            + 0.10 * continuity_score
            + 0.025 * min(high_count / total_episodes, 1.0)
            + 0.025 * min(voice_count / total_episodes, 1.0)
        )
        scored_rows.append((score, row))

    scored_rows.sort(
        key=lambda item: (
            -item[0],
            -int(item[1].get("distinct_episode_count") or 0),
            str(item[1].get("display_name") or ""),
        )
    )
    top_score = scored_rows[0][0] if scored_rows else 0.0
    second_score = scored_rows[1][0] if len(scored_rows) > 1 else 0.0
    second_focal_count = (
        int(dict(scored_rows[1][1].get("episode_focal_evidence") or {}).get("episode_count") or 0)
        if len(scored_rows) > 1
        else 0
    )
    second_work_protagonist_count = (
        int(dict(scored_rows[1][1].get("work_protagonist_evidence") or {}).get("episode_count") or 0)
        if len(scored_rows) > 1
        else 0
    )
    second_distinct_episode_count = (
        int(scored_rows[1][1].get("distinct_episode_count") or 0)
        if len(scored_rows) > 1
        else 0
    )
    main_candidates = []
    for rank, (score, row) in enumerate(scored_rows, start=1):
        work_protagonist_count = int(dict(row.get("work_protagonist_evidence") or {}).get("episode_count") or 0)
        focal_count = int(dict(row.get("episode_focal_evidence") or {}).get("episode_count") or 0)
        role_counts = dict(row.get("episode_role_counts") or {})
        distinct_episode_count = int(row.get("distinct_episode_count") or 0)
        top_second_ratio = round(top_score / second_score, 2) if second_score else None
        blocking_identity_conflict_reasons = _inventory_identity_blocking_conflict_reasons(row)
        role_like_persona_main_eligible = _has_strong_role_like_persona_evidence(row)
        identity_main_eligible = _inventory_identity_is_public_resolved(row) or role_like_persona_main_eligible
        row["protagonist_evidence"] = {
            "score": round(score, 4),
            "rank": rank,
            "top_second_ratio": top_second_ratio,
        }
        row["work_role"] = "unknown"
        row["role_confidence"] = "low"
        row["classification_status"] = "INCOMPLETE" if distinct_episode_count == 0 else "NEEDS_REVIEW"
        row["review_reasons"] = list(row.get("identity_conflict_reasons") or [])
        if focal_count <= 0 and distinct_episode_count >= 3:
            row["work_role"] = "major_character"
            row["classification_status"] = "AUTO_RESOLVED"
            row["role_confidence"] = "medium"
        elif distinct_episode_count >= 3 or focal_count >= 1 or int(role_counts.get("lead") or 0) >= 2:
            row["work_role"] = "major_character"
            row["role_confidence"] = "medium" if distinct_episode_count >= 3 else "low"
        dominant_long_running_top = (
            rank == 1
            and score >= CHARACTER_INVENTORY_V3_DOMINANT_PROTAGONIST_SCORE_THRESHOLD
            and distinct_episode_count >= max(
                6,
                int(total_episodes * CHARACTER_INVENTORY_V3_DOMINANT_PROTAGONIST_MIN_COVERAGE),
            )
            and (
                second_score <= 0
                or score >= second_score * CHARACTER_INVENTORY_V3_DOMINANT_PROTAGONIST_MIN_RATIO
                or (
                    work_protagonist_count > second_work_protagonist_count
                    and focal_count > second_focal_count
                )
            )
            and (
                work_protagonist_count > second_work_protagonist_count
                or focal_count > second_focal_count
                or (
                    second_distinct_episode_count > 0
                    and distinct_episode_count >= second_distinct_episode_count * 1.5
                )
            )
        )
        if (
            rank == 1
            and identity_main_eligible
            and (not bool(row.get("is_generic_display_name")) or role_like_persona_main_eligible)
            and not blocking_identity_conflict_reasons
            and work_protagonist_count >= 2
            and (
                score >= CHARACTER_INVENTORY_V3_PROTAGONIST_SCORE_THRESHOLD
                or dominant_long_running_top
            )
            and (
                second_score <= 0
                or score >= second_score * 2
                or work_protagonist_count > second_work_protagonist_count
                or focal_count > second_focal_count
                or dominant_long_running_top
            )
        ):
            main_candidates.append(row)
        elif rank <= 2 and second_score > 0 and top_score < second_score * 2:
            row["review_reasons"] = sorted(set(list(row.get("review_reasons") or []) + ["AMBIGUOUS_TOP_CANDIDATES"]))

    if protagonist_resolution is None:
        if len(main_candidates) == 1:
            main_row = main_candidates[0]
            main_row["work_role"] = "main_protagonist"
            main_row["role_confidence"] = "high"
            main_row["classification_status"] = "AUTO_RESOLVED"
            main_row["review_reasons"] = []
        elif len(main_candidates) > 1:
            for row in main_candidates:
                row["review_reasons"] = sorted(set(list(row.get("review_reasons") or []) + ["MULTIPLE_MAIN_PROTAGONISTS"]))
    else:
        _apply_work_protagonist_resolution(rows, protagonist_resolution)

    _apply_locked_work_protagonist_rows(rows, list(locked_protagonist_rows or []))
    _apply_protagonist_identity_groups(rows)

    for row in rows:
        is_protagonist = str(row.get("work_role") or "") == "main_protagonist"
        voice_counts = dict(row.get("voice_mode_counts") or {})
        speaking_episode_count = int(voice_counts.get("dialogue") or 0) + int(voice_counts.get("monologue") or 0)
        identity_status = str(row.get("identity_status") or "")
        blocking_identity_conflict_reasons = _inventory_identity_blocking_conflict_reasons(row)
        distinct_episode_count = int(row.get("distinct_episode_count") or 0)
        role_like_persona_ready = _has_strong_role_like_persona_evidence(row)
        if (
            (identity_status in {"RESOLVED_NAMED", "CONFLICT"} or role_like_persona_ready)
            and not blocking_identity_conflict_reasons
            and speaking_episode_count >= 2
        ):
            rp_status = "summary_ready"
        elif distinct_episode_count >= 1 and speaking_episode_count >= 1:
            rp_status = "summary_limited"
        else:
            rp_status = "insufficient"
        row["is_protagonist"] = is_protagonist
        row["protagonist_confidence"] = str(row.get("role_confidence") or "low") if is_protagonist else "low"
        row["rp_signal_quality"] = {
            "status": rp_status,
            "evidence_source": "episode_summary_voice_mode",
            "strict_chat_ready": False,
            "speaking_episode_count": speaking_episode_count,
            "needs_review": bool(row.get("review_reasons")) or str(row.get("classification_status") or "") != "AUTO_RESOLVED",
        }
        display_safety = build_inventory_display_safety(row)
        row["display_safety"] = display_safety
        row["public_chat_eligible"] = is_public_chat_inventory_candidate(row)
        row["public_slot_eligible"] = is_public_slot_inventory_candidate(row)
        row["identity_surface"] = build_inventory_identity_surface(row)
        row["reveal_boundary"] = build_inventory_reveal_boundary(row)
        row["read_range_state_snapshot"] = build_inventory_read_range_state_snapshot(row)
        row["interaction_affordance_v1"] = build_inventory_interaction_affordance_v1(row)
        row["adjacent_event_seed_v1"] = build_inventory_adjacent_event_seed_v1(row)
        row["pov_and_protagonist_centrality_v1"] = build_inventory_pov_and_protagonist_centrality_v1(row)
        row["voice_contract_v1"] = build_inventory_voice_contract_v1(row)
        row["chat_readiness_v1"] = build_inventory_chat_readiness_v1(row)


def build_inventory_display_safety(row: dict[str, object]) -> dict[str, object]:
    display_name = str(row.get("display_name") or "").strip()
    identity_status = str(row.get("identity_status") or "")
    entity_kind = str(row.get("entity_kind") or "").strip().lower()
    role_like_persona_ready = _has_strong_role_like_persona_evidence(row)
    if _display_label_has_hard_public_block(display_name):
        return {"status": "fail", "reason": "generic_display_name" if is_generic_character_label(display_name) else "role_or_relation_label"}
    if is_generic_character_label(display_name):
        if role_like_persona_ready:
            return {"status": "pass", "reason": "stable_persona_identity"}
        return {"status": "fail", "reason": "generic_display_name"}
    if _identity_claim_label_is_blocked(display_name):
        if role_like_persona_ready:
            return {"status": "pass", "reason": "stable_persona_identity"}
        return {"status": "fail", "reason": "role_or_relation_label"}
    if "first_person_identity_unverified" in list(row.get("identity_conflict_reasons") or []):
        return {"status": "review", "reason": "first_person_identity_unverified"}
    if identity_status == "UNRESOLVED" or (identity_status == "CONFLICT" and not _inventory_identity_is_public_resolved(row)):
        if role_like_persona_ready:
            return {"status": "pass", "reason": "stable_persona_identity"}
        return {"status": "review", "reason": "identity_not_resolved"}
    if identity_status == "RESOLVED_STABLE_ROLE" or entity_kind == "stable_role":
        if role_like_persona_ready:
            return {"status": "pass", "reason": "stable_persona_identity"}
        return {"status": "review", "reason": "stable_role_identity"}
    return {"status": "pass", "reason": "resolved_named_identity"}


def is_public_chat_inventory_candidate(row: dict[str, object]) -> bool:
    display_safety = dict(row.get("display_safety") or build_inventory_display_safety(row))
    if str(display_safety.get("status") or "") != "pass":
        return False
    if not (_inventory_identity_is_public_resolved(row) or _has_strong_role_like_persona_evidence(row)):
        return False
    work_role = str(row.get("work_role") or "")
    if work_role not in {"main_protagonist", "major_character"}:
        return False
    rp_signal_status = str(dict(row.get("rp_signal_quality") or {}).get("status") or "")
    minimum_episode_count = 3 if work_role == "main_protagonist" and rp_signal_status != "summary_ready" else 2
    if int(row.get("distinct_episode_count") or 0) < minimum_episode_count:
        return False
    if work_role == "main_protagonist":
        return True
    if rp_signal_status != "summary_ready":
        return False
    voice_counts = dict(row.get("voice_mode_counts") or {})
    speaking_episode_count = int(voice_counts.get("dialogue") or 0) + int(voice_counts.get("monologue") or 0)
    return speaking_episode_count >= 1 or int(row.get("relation_episode_count") or 0) >= 2


def is_public_slot_inventory_candidate(row: dict[str, object]) -> bool:
    if not is_public_chat_inventory_candidate(row):
        return False
    if bool(dict(row.get("rp_signal_quality") or {}).get("needs_review")):
        return False
    if int(row.get("distinct_episode_count") or 0) < 3:
        return False
    if str(row.get("work_role") or "") == "main_protagonist":
        return True
    voice_counts = dict(row.get("voice_mode_counts") or {})
    speaking_episode_count = int(voice_counts.get("dialogue") or 0) + int(voice_counts.get("monologue") or 0)
    return speaking_episode_count >= 2 or int(row.get("relation_episode_count") or 0) >= 2


def build_inventory_identity_surface(row: dict[str, object]) -> dict[str, object]:
    display_name = str(row.get("display_name") or "").strip()
    display_safety = dict(row.get("display_safety") or build_inventory_display_safety(row))
    addressable_names: list[str] = []
    social_call_names = list(row.get("social_call_names") or [])
    persona_names = list(row.get("persona_names") or [])
    address_name_candidates = [display_name, *social_call_names, *persona_names]
    if not social_call_names and not persona_names:
        address_name_candidates.extend(list(row.get("narration_names") or []))
    for value in address_name_candidates:
        if _identity_claim_label_is_blocked(str(value or "")):
            continue
        _append_unique_text(addressable_names, str(value or ""), limit=6)

    private_identity_names: list[str] = []
    for value in list(row.get("real_names") or []):
        normalized_value = normalize_signal_entity_label(str(value or ""))
        if not normalized_value:
            continue
        if any(normalize_signal_entity_label(name) == normalized_value for name in addressable_names):
            continue
        if _identity_claim_label_is_blocked(str(value or "")):
            continue
        _append_unique_text(private_identity_names, str(value or ""), limit=6)

    reveal_state = "public"
    if private_identity_names:
        reveal_state = "known_to_self"
    if str(display_safety.get("status") or "") != "pass":
        reveal_state = "ambiguous"
    elif str(row.get("identity_status") or "") in {"UNRESOLVED", "CONFLICT"}:
        reveal_state = "ambiguous"

    confidence = "high" if str(row.get("identity_confidence") or "") == "high" and reveal_state == "public" else "medium"
    if reveal_state == "ambiguous":
        confidence = "low"

    return {
        "chat_display_name": display_name,
        "addressable_names": addressable_names[:6],
        "public_role_titles": [
            name
            for name in list(row.get("social_call_names") or [])[:4]
            if name in addressable_names and name != display_name
        ],
        "private_identity_names": private_identity_names[:6],
        "forbidden_until_revealed": private_identity_names[:6],
        "reveal_state": reveal_state,
        "reveal_audience": "general_public" if reveal_state == "public" else "self_only" if reveal_state == "known_to_self" else "unknown",
        "confidence": confidence,
        "evidence_episode_nos": list(row.get("evidence_episode_nos") or [])[:8],
    }


def build_inventory_reveal_boundary(row: dict[str, object]) -> dict[str, object]:
    identity_surface = dict(row.get("identity_surface") or build_inventory_identity_surface(row))
    return {
        "allowed_address_names": list(identity_surface.get("addressable_names") or [])[:6],
        "must_not_address_as": list(identity_surface.get("forbidden_until_revealed") or [])[:6],
        "reveal_state": str(identity_surface.get("reveal_state") or "ambiguous"),
        "identity_spoiler_risk": "high"
        if list(identity_surface.get("forbidden_until_revealed") or [])
        else "medium"
        if str(identity_surface.get("reveal_state") or "") == "ambiguous"
        else "low",
    }


def build_inventory_read_range_state_snapshot(row: dict[str, object]) -> dict[str, object]:
    identity_surface = dict(row.get("identity_surface") or build_inventory_identity_surface(row))
    reveal_boundary = dict(row.get("reveal_boundary") or build_inventory_reveal_boundary(row))
    voice_counts = dict(row.get("voice_mode_counts") or {})
    scene_counts = dict(row.get("scene_weight_counts") or {})
    role_counts = dict(row.get("episode_role_counts") or {})
    evidence_episode_nos = [
        int(value)
        for value in list(row.get("evidence_episode_nos") or [])
        if int(value or 0) > 0
    ]
    public_role_titles = list(identity_surface.get("public_role_titles") or [])
    private_identity_names = list(identity_surface.get("private_identity_names") or [])
    social_call_names = list(row.get("social_call_names") or [])
    persona_names = list(row.get("persona_names") or [])
    identity_variant = "normal"
    if private_identity_names and (social_call_names or persona_names):
        identity_variant = "alternate_public_identity"
    elif private_identity_names:
        identity_variant = "hidden_true_name"
    elif str(row.get("entity_kind") or "").strip().lower() == "stable_role":
        identity_variant = "role_identity"

    return {
        "schema_version": "read_range_state_snapshot_v1",
        "stage": "inventory_signal",
        "as_of_episode_no": int(row.get("latest_seen_episode_no") or 0),
        "valid_episode_range": {
            "from": int(row.get("first_seen_episode_no") or 0),
            "to": int(row.get("latest_seen_episode_no") or 0),
        },
        "current_identity": {
            "display_name": str(identity_surface.get("chat_display_name") or row.get("display_name") or ""),
            "social_name": str((social_call_names or persona_names or [None])[0] or "") or None,
            "private_true_name": str((private_identity_names or [None])[0] or "") or None,
            "title_or_role_name": str((public_role_titles or [None])[0] or "") or None,
            "identity_variant": identity_variant,
            "reveal_state": str(reveal_boundary.get("reveal_state") or "ambiguous"),
        },
        "current_status": {
            "work_role": str(row.get("work_role") or ""),
            "entity_kind": str(row.get("entity_kind") or ""),
            "role_confidence": str(row.get("role_confidence") or ""),
            "dominant_action_tags": list(row.get("dominant_action_tags") or [])[:5],
            "dominant_affect_tags": list(row.get("dominant_affect_tags") or [])[:5],
        },
        "evidence_counts": {
            "distinct_episode_count": int(row.get("distinct_episode_count") or 0),
            "lead_episode_count": int(role_counts.get("lead") or 0),
            "high_scene_episode_count": int(scene_counts.get("high") or 0),
            "dialogue_episode_count": int(voice_counts.get("dialogue") or 0),
            "monologue_episode_count": int(voice_counts.get("monologue") or 0),
            "relation_episode_count": int(row.get("relation_episode_count") or 0),
        },
        "evidence_episode_nos": evidence_episode_nos[:8],
        "forbidden_identity_terms": list(reveal_boundary.get("must_not_address_as") or [])[:6],
    }


def _inventory_action_tags(row: dict[str, object]) -> list[str]:
    return [str(value).strip() for value in list(row.get("dominant_action_tags") or []) if str(value).strip()]


def _inventory_has_action_tag_family(row: dict[str, object], keywords: set[str]) -> bool:
    return any(keyword in tag for tag in _inventory_action_tags(row) for keyword in keywords)


def _inventory_action_tag_family_count(row: dict[str, object], keywords: set[str]) -> int:
    return sum(
        1
        for tag in _inventory_action_tags(row)
        if any(keyword in tag for keyword in keywords)
    )


def _inventory_primary_interaction_role(row: dict[str, object]) -> tuple[str, str]:
    relation_count = int(row.get("relation_episode_count") or 0)
    investigation_count = _inventory_action_tag_family_count(row, {"조사", "수사", "추적", "탐색", "단서", "정보", "열람", "잠입", "추리", "진단", "치료", "정체"})
    combat_count = _inventory_action_tag_family_count(row, {"전투", "훈련", "수련", "생존", "방어", "공격", "제압", "처형", "검기", "테이밍", "소환", "각성"})
    if investigation_count > 0 and investigation_count >= combat_count:
        return "scene_clue_holder", "장면에 단서를 들고 엮인 임시 조력자"
    if combat_count > 0:
        return "field_support", "현장 보조자"
    if relation_count >= 2:
        return "temporary_ally", "낮은 신뢰의 임시 동행자"
    return "temporary_helper_at_scene", "장면에 약하게 엮인 임시 조력자"


def build_inventory_interaction_affordance_v1(row: dict[str, object]) -> dict[str, object]:
    role_key, role_label = _inventory_primary_interaction_role(row)
    reveal_boundary = dict(row.get("reveal_boundary") or build_inventory_reveal_boundary(row))
    return {
        "schema_version": "interaction_affordance_v1",
        "stage": "inventory_signal",
        "preferred_user_role_key": role_key,
        "user_role_options": [
            {
                "role_key": role_key,
                "role_label_ko": role_label,
                "entry_reason": "읽은 범위 안의 현재 사건에 약하게 엮여 있고, 주인공의 다음 판단에 작은 도움을 줄 수 있다.",
                "why_protagonist_does_not_immediately_remove_user": "유저가 장면 압력, 단서, 선택지 중 하나와 연결되어 있어 즉시 배제하기보다 짧게 활용하는 편이 자연스럽다.",
                "default_trust": "situational",
                "suspicion_ceiling": "light",
                "user_task": "주인공의 현재 행동을 보조할 단서 확인, 선택지 제시, 짧은 응답 중 하나를 맡는다.",
                "user_success_condition": "주인공이 다음 행동을 정할 만큼 장면 정보나 압력이 한 단계 전진한다.",
                "user_failure_risk": "응답이 짧거나 거절해도 심문 루프 대신 작은 방해, 단서, 시간 압박으로 장면을 전진시킨다.",
                "address_rule_from_pc_to_user": "원작 네임드나 후반 관계로 확정하지 말고 장면 속 약한 관계로만 대한다.",
                "user_must_not_know": list(reveal_boundary.get("must_not_address_as") or [])[:6],
            }
        ],
        "prohibited_user_roles": [
            "원작 기존 네임드",
            "작가",
            "독자",
            "시스템",
            "미래를 다 아는 존재",
            "주인공의 확정된 연인/가족/절친",
        ],
    }


def build_inventory_adjacent_event_seed_v1(row: dict[str, object]) -> dict[str, object]:
    action_tags = _inventory_action_tags(row)
    affect_tags = [str(value).strip() for value in list(row.get("dominant_affect_tags") or []) if str(value).strip()]
    investigation_count = _inventory_action_tag_family_count(row, {"조사", "수사", "추적", "탐색", "단서", "정보", "열람", "잠입", "추리", "진단", "치료", "정체"})
    combat_count = _inventory_action_tag_family_count(row, {"전투", "방어", "공격", "생존", "제압", "처형", "검기"})
    trial_count = _inventory_action_tag_family_count(row, {"훈련", "수련", "테이밍", "소환", "각성", "시험", "오디션", "공연"})
    if investigation_count > 0 and investigation_count >= combat_count and investigation_count >= trial_count:
        conflict_vector = "hidden_clue"
    elif combat_count > 0 and combat_count >= trial_count:
        conflict_vector = "minor_attack"
    elif trial_count > 0:
        conflict_vector = "test_or_trial"
    else:
        conflict_vector = "unexpected_visitor"
    role_key, role_label = _inventory_primary_interaction_role(row)
    return {
        "schema_version": "adjacent_event_seed_v1",
        "stage": "inventory_signal",
        "anchor_episode_range": {
            "from": int(row.get("first_seen_episode_no") or 0),
            "to": int(row.get("latest_seen_episode_no") or 0),
        },
        "grounded_situation": "읽은 범위 안에서 확인된 주인공의 행동/관계/압력만 앵커로 쓴다.",
        "new_incident_is_adjacent_not_canon": True,
        "conflict_vector": conflict_vector,
        "allowed_intensity": "action" if conflict_vector in {"minor_attack", "test_or_trial"} else "investigation" if conflict_vector == "hidden_clue" else "emotional" if affect_tags else "banter",
        "user_entry_point": role_label,
        "protagonist_first_move": "주인공이 현재 압력이나 단서를 먼저 짚고, 유저에게 짧은 선택 또는 협력 hook을 건다.",
        "canon_noninterference_rule": "원작 핵심 사건/결말/폭로를 재현하거나 바꾸지 말고, 같은 세계관에서 생긴 작은 곁가지 사건만 진행한다.",
        "forbidden_canon_outcomes": ["원작 결말 확정", "후반 정체 폭로", "주요 관계 급진전", "원작 대사 복붙"],
        "source_tags": action_tags[:5],
    }


def build_inventory_pov_and_protagonist_centrality_v1(row: dict[str, object]) -> dict[str, object]:
    work_role = str(row.get("work_role") or "").strip()
    first_seen_episode_no = int(row.get("first_seen_episode_no") or 0)
    latest_seen_episode_no = int(row.get("latest_seen_episode_no") or 0)
    focal_count = int(dict(row.get("episode_focal_evidence") or {}).get("episode_count") or 0)
    work_protagonist_count = int(dict(row.get("work_protagonist_evidence") or {}).get("episode_count") or 0)
    first_person_count = int(dict(row.get("first_person_evidence") or {}).get("episode_count") or 0)

    if work_role == "main_protagonist":
        if first_seen_episode_no <= 0:
            protagonist_presence = "unknown"
        elif first_seen_episode_no <= 1:
            protagonist_presence = "active_from_start"
        elif first_seen_episode_no <= 3:
            protagonist_presence = "late_entry_after_prologue"
        else:
            protagonist_presence = "late_entry"
    elif work_role == "major_character":
        protagonist_presence = "major_non_protagonist"
    else:
        protagonist_presence = "not_protagonist"

    hold_before_episode_no = (
        first_seen_episode_no
        if work_role == "main_protagonist" and first_seen_episode_no > 1
        else None
    )
    expose_policy = "allow"
    if work_role != "main_protagonist":
        expose_policy = "reject_for_main_protagonist_chat"
    elif hold_before_episode_no:
        expose_policy = "hold_until_presence_episode"

    return {
        "schema_version": "pov_and_protagonist_centrality_v1",
        "stage": "inventory_signal",
        "protagonist_presence": protagonist_presence,
        "first_seen_episode_no": first_seen_episode_no,
        "latest_seen_episode_no": latest_seen_episode_no,
        "hold_before_episode_no": hold_before_episode_no,
        "expose_policy": expose_policy,
        "active_pov_owner_character_key": str(row.get("canonical_character_key") or "") if first_person_count > 0 else None,
        "true_main_protagonist_character_key": str(row.get("canonical_character_key") or "") if work_role == "main_protagonist" else None,
        "evidence_counts": {
            "episode_focal_count": focal_count,
            "work_protagonist_hint_count": work_protagonist_count,
            "first_person_count": first_person_count,
            "distinct_episode_count": int(row.get("distinct_episode_count") or 0),
        },
    }


def build_inventory_voice_contract_v1(row: dict[str, object]) -> dict[str, object]:
    voice_counts = dict(row.get("voice_mode_counts") or {})
    identity_surface = dict(row.get("identity_surface") or build_inventory_identity_surface(row))
    reveal_boundary = dict(row.get("reveal_boundary") or build_inventory_reveal_boundary(row))
    address_terms: list[str] = []
    for value in [
        *list(identity_surface.get("addressable_names") or []),
        *list(identity_surface.get("public_role_titles") or []),
        *list(row.get("social_call_names") or []),
        *list(row.get("persona_names") or []),
    ]:
        _append_unique_text(address_terms, str(value or ""), limit=8)

    speaking_episode_count = int(voice_counts.get("dialogue") or 0) + int(voice_counts.get("monologue") or 0)
    speech_register = "unknown_inventory_signal"
    if address_terms and any(_is_honorific_address_term(term) for term in address_terms):
        speech_register = "honorific_surface_present"
    elif speaking_episode_count >= 2:
        speech_register = "dialogue_evidence_present"

    forbidden_address_terms: list[str] = []
    for value in [
        *list(reveal_boundary.get("must_not_address_as") or []),
        *list(identity_surface.get("private_identity_names") or []),
        *list(identity_surface.get("forbidden_until_revealed") or []),
    ]:
        _append_unique_text(forbidden_address_terms, str(value or ""), limit=8)

    return {
        "schema_version": "voice_contract_v1",
        "stage": "inventory_signal",
        "speech_register": speech_register,
        "address_terms": address_terms[:8],
        "addressing_contract_v1": build_addressing_contract_v1(
            address_terms=address_terms,
            forbidden_address_terms=forbidden_address_terms,
            speech_register=speech_register,
        ),
        "evidence_counts": {
            "dialogue_episode_count": int(voice_counts.get("dialogue") or 0),
            "monologue_episode_count": int(voice_counts.get("monologue") or 0),
            "speaking_episode_count": speaking_episode_count,
        },
        "must_preserve": [
            "한국어 존반말/호칭 거리감",
            "원문 대사 근거가 있는 말투",
            "관계에 따른 호칭 변화",
        ],
        "forbidden_speech_patterns": [
            "무엇을 도와드릴까요",
            "안녕하세요",
            "제가 도와드릴게요",
            "작품에 대해 설명하자면",
        ],
    }


def build_inventory_chat_readiness_v1(row: dict[str, object]) -> dict[str, object]:
    voice_counts = dict(row.get("voice_mode_counts") or {})
    scene_counts = dict(row.get("scene_weight_counts") or {})
    role_counts = dict(row.get("episode_role_counts") or {})
    display_safety = dict(row.get("display_safety") or build_inventory_display_safety(row))
    identity_surface = dict(row.get("identity_surface") or build_inventory_identity_surface(row))
    reveal_boundary = dict(row.get("reveal_boundary") or build_inventory_reveal_boundary(row))
    read_range_state = dict(row.get("read_range_state_snapshot") or build_inventory_read_range_state_snapshot(row))
    interaction_affordance = dict(row.get("interaction_affordance_v1") or build_inventory_interaction_affordance_v1(row))
    adjacent_event_seed = dict(row.get("adjacent_event_seed_v1") or build_inventory_adjacent_event_seed_v1(row))
    pov_centrality = dict(row.get("pov_and_protagonist_centrality_v1") or build_inventory_pov_and_protagonist_centrality_v1(row))
    voice_contract = dict(row.get("voice_contract_v1") or build_inventory_voice_contract_v1(row))

    speaking_episode_count = int(voice_counts.get("dialogue") or 0) + int(voice_counts.get("monologue") or 0)
    distinct_episode_count = int(row.get("distinct_episode_count") or 0)
    scope_key = str(row.get("canonical_character_key") or "").strip()
    work_role = str(row.get("work_role") or "").strip()
    reveal_state = str(reveal_boundary.get("reveal_state") or "").strip()

    required_passes = {
        "has_valid_scope_key": bool(scope_key),
        "has_character_work_match": work_role in {"main_protagonist", "major_character"},
        "has_public_display_safety": str(display_safety.get("status") or "") == "pass",
        "has_voice_evidence": speaking_episode_count >= 1,
        "has_strict_voice_evidence": speaking_episode_count >= 2,
        "has_read_range_state": distinct_episode_count >= 2,
        "has_identity_surface": bool(identity_surface.get("chat_display_name")) and bool(list(identity_surface.get("addressable_names") or [])),
        "has_reveal_boundary": reveal_state in {"public", "known_to_self"},
        "has_read_range_state_snapshot": bool(read_range_state.get("as_of_episode_no")),
        "has_interaction_affordance": bool(interaction_affordance.get("preferred_user_role_key")),
        "has_adjacent_event_seed": bool(adjacent_event_seed.get("new_incident_is_adjacent_not_canon")),
        "has_pov_centrality": str(pov_centrality.get("protagonist_presence") or "") not in {"", "unknown", "not_protagonist"},
        "has_voice_contract": bool(voice_contract.get("speech_register")) and speaking_episode_count >= 1,
    }

    block_reasons: list[str] = []
    if not required_passes["has_valid_scope_key"]:
        block_reasons.append("scope_key_invalid")
    if not required_passes["has_character_work_match"]:
        block_reasons.append("not_major_character")
    if not required_passes["has_public_display_safety"]:
        block_reasons.append("display_safety_not_pass")
    if not required_passes["has_voice_evidence"]:
        block_reasons.append("insufficient_voice_evidence")
    if not required_passes["has_read_range_state"]:
        block_reasons.append("read_range_too_thin")
    if not required_passes["has_identity_surface"]:
        block_reasons.append("identity_surface_missing")
    if not required_passes["has_reveal_boundary"]:
        block_reasons.append("identity_unstable_without_boundary")
    if not required_passes["has_interaction_affordance"]:
        block_reasons.append("no_safe_user_role")
    if not required_passes["has_adjacent_event_seed"]:
        block_reasons.append("no_adjacent_event_seed")
    if not required_passes["has_pov_centrality"]:
        block_reasons.append("pov_owner_unclear")
    if not required_passes["has_voice_contract"]:
        block_reasons.append("voice_contract_missing")
    if not bool(row.get("public_chat_eligible")) and not block_reasons:
        block_reasons.append("public_chat_gate_failed")

    hard_reject_reasons = {
        "scope_key_invalid",
        "display_safety_not_pass",
        "identity_surface_missing",
        "identity_unstable_without_boundary",
        "not_major_character",
    }
    exposure_decision = (
        "eligible"
        if bool(row.get("public_chat_eligible"))
        else "reject"
        if any(reason in hard_reject_reasons for reason in block_reasons)
        else "hold"
    )

    confidence = 0.0
    if exposure_decision == "eligible":
        confidence = 0.9 if bool(row.get("public_slot_eligible")) else 0.75
    elif exposure_decision == "hold":
        confidence = 0.45

    return {
        "schema_version": "chat_readiness_v1",
        "stage": "inventory_signal",
        "exposure_decision": exposure_decision,
        "public_slot_allowed": bool(row.get("public_slot_eligible")),
        "character_chat_allowed": bool(row.get("public_chat_eligible")),
        "confidence": confidence,
        "block_reasons": block_reasons,
        "evidence_counts": {
            "direct_dialogue_episodes": int(voice_counts.get("dialogue") or 0),
            "monologue_episodes": int(voice_counts.get("monologue") or 0),
            "speaking_episode_count": speaking_episode_count,
            "lead_episode_count": int(role_counts.get("lead") or 0),
            "high_scene_episode_count": int(scene_counts.get("high") or 0),
            "scene_anchor_episode_count": distinct_episode_count,
            "identity_surface_evidence_count": len(list(row.get("evidence_episode_nos") or [])),
            "relationship_evidence_count": int(row.get("relation_episode_count") or 0),
        },
        "required_passes": required_passes,
    }


def _work_protagonist_resolution_candidate_is_selectable(row: dict[str, object]) -> bool:
    entity_kind = str(row.get("entity_kind") or "person").strip().lower()
    if entity_kind not in {"person", "stable_role"}:
        return False
    if _inventory_identity_blocking_conflict_reasons(row):
        return False

    role_like_persona_ready = _has_strong_role_like_persona_evidence(row)
    display_safety = dict(row.get("display_safety") or build_inventory_display_safety(row))
    if str(display_safety.get("status") or "") != "pass":
        return False
    if _display_label_has_hard_public_block(str(row.get("display_name") or "")) and not role_like_persona_ready:
        return False
    return _inventory_identity_is_public_resolved(row) or role_like_persona_ready


def _has_duplicate_canonical_key_conflict(row: dict[str, object]) -> bool:
    reasons = set(str(reason) for reason in list(row.get("identity_conflict_reasons") or []))
    reasons.update(str(reason) for reason in list(row.get("review_reasons") or []))
    return "duplicate_canonical_key" in reasons or ":dup:" in str(row.get("canonical_character_key") or "")


def _append_unique(values: list[str], value: str) -> None:
    text = str(value or "").strip()
    if text and text not in values:
        values.append(text)


def _bounded_episode_count_sum(
    rows: list[dict[str, object]],
    getter,
    *,
    total_episodes: int,
) -> int:
    return min(sum(max(int(getter(row) or 0), 0) for row in rows), max(total_episodes, 1))


def _collect_compacted_evidence_episode_nos(rows: list[dict[str, object]]) -> list[int]:
    episode_nos = sorted(
        {
            int(no)
            for row in rows
            for no in list(row.get("evidence_episode_nos") or [])
            if int(no or 0) > 0
        }
    )
    return episode_nos


def _score_compacted_work_protagonist_candidate(row: dict[str, object], *, total_episodes: int) -> float:
    total = max(total_episodes, 1)
    distinct_episode_count = int(row.get("distinct_episode_count") or 0)
    work_protagonist_count = int(dict(row.get("work_protagonist_evidence") or {}).get("episode_count") or 0)
    focal_count = int(dict(row.get("episode_focal_evidence") or {}).get("episode_count") or 0)
    first_person_count = int(dict(row.get("first_person_evidence") or {}).get("episode_count") or 0)
    role_counts = dict(row.get("episode_role_counts") or {})
    scene_counts = dict(row.get("scene_weight_counts") or {})
    voice_counts = dict(row.get("voice_mode_counts") or {})
    lead_count = int(role_counts.get("lead") or 0)
    high_count = int(scene_counts.get("high") or 0)
    voice_count = int(voice_counts.get("dialogue") or 0) + int(voice_counts.get("monologue") or 0)
    coverage_score = min(distinct_episode_count / total, 1.0)
    continuity_score = 1.0 if distinct_episode_count >= 3 else 0.5 if distinct_episode_count >= 2 else 0.0
    return round(
        0.50 * min(work_protagonist_count / total, 1.0)
        + 0.10 * min(lead_count / total, 1.0)
        + 0.15 * min(first_person_count / total, 1.0)
        + 0.10 * coverage_score
        + 0.10 * continuity_score
        + 0.025 * min(high_count / total, 1.0)
        + 0.025 * min(voice_count / total, 1.0),
        4,
    )


def _build_compacted_work_protagonist_duplicate_row(
    rows: list[dict[str, object]],
    *,
    total_episodes: int,
    other_display_labels: set[str],
) -> dict[str, object]:
    representative = dict(rows[0])
    representative_key = str(representative.get("canonical_character_key") or "")
    display_label = normalize_signal_entity_label(str(representative.get("display_name") or ""))
    rows_with_cross_candidate_aliases: set[str] = set()
    for row in rows:
        for alias in list(row.get("aliases") or []):
            alias_label = normalize_signal_entity_label(str(alias or ""))
            if alias_label and alias_label != display_label and alias_label in other_display_labels:
                rows_with_cross_candidate_aliases.add(str(row.get("canonical_character_key") or ""))

    evidence_rows = [
        row
        for row in rows
        if str(row.get("canonical_character_key") or "") == representative_key
        or str(row.get("canonical_character_key") or "") not in rows_with_cross_candidate_aliases
    ]
    if not evidence_rows:
        evidence_rows = [rows[0]]
    evidence_row_keys = {str(row.get("canonical_character_key") or "") for row in evidence_rows}
    ignored_cross_alias_keys = sorted(rows_with_cross_candidate_aliases - evidence_row_keys)

    evidence_episode_nos = _collect_compacted_evidence_episode_nos(evidence_rows)
    distinct_episode_count = max(
        len(evidence_episode_nos),
        max(int(row.get("distinct_episode_count") or 0) for row in evidence_rows),
    )
    first_seen_candidates = [int(row.get("first_seen_episode_no") or 0) for row in evidence_rows if int(row.get("first_seen_episode_no") or 0) > 0]
    latest_seen_episode_no = max(int(row.get("latest_seen_episode_no") or 0) for row in evidence_rows)

    aliases: list[str] = []
    removed_cross_candidate_aliases: list[str] = []
    for row in rows:
        _append_unique(aliases, str(row.get("display_name") or ""))
        for alias in list(row.get("aliases") or []):
            alias_label = normalize_signal_entity_label(str(alias or ""))
            if alias_label and alias_label != display_label and alias_label in other_display_labels:
                _append_unique(removed_cross_candidate_aliases, str(alias or ""))
                continue
            _append_unique(aliases, str(alias or ""))

    role_counts = {
        role: _bounded_episode_count_sum(
            evidence_rows,
            lambda row, role=role: dict(row.get("episode_role_counts") or {}).get(role),
            total_episodes=total_episodes,
        )
        for role in ["lead", "counterpart", "support", "obstacle"]
    }
    voice_counts = {
        mode: _bounded_episode_count_sum(
            evidence_rows,
            lambda row, mode=mode: dict(row.get("voice_mode_counts") or {}).get(mode),
            total_episodes=total_episodes,
        )
        for mode in ["dialogue", "monologue", "narration_only"]
    }
    scene_counts = {
        weight: _bounded_episode_count_sum(
            evidence_rows,
            lambda row, weight=weight: dict(row.get("scene_weight_counts") or {}).get(weight),
            total_episodes=total_episodes,
        )
        for weight in ["high", "medium", "low"]
    }
    identity_conflict_reasons = sorted(
        {
            str(reason)
            for row in rows
            for reason in list(row.get("identity_conflict_reasons") or [])
            if str(reason) and str(reason) != "duplicate_canonical_key"
        }
    )
    review_reasons = sorted(
        {
            str(reason)
            for row in rows
            for reason in list(row.get("review_reasons") or [])
            if str(reason)
            and str(reason) not in {"duplicate_canonical_key", "DUPLICATE_PUBLIC_DISPLAY_NAME"}
        }
        | {"DUPLICATE_DISPLAY_COMPACTED"}
    )

    representative["aliases"] = aliases[:16]
    representative["identity_status"] = str(representative.get("identity_status") or "")
    if str(representative.get("identity_status") or "") == "CONFLICT" and not identity_conflict_reasons:
        representative["identity_status"] = "RESOLVED_NAMED"
    representative["identity_conflict_reasons"] = identity_conflict_reasons
    representative["review_reasons"] = review_reasons
    representative["first_seen_episode_no"] = min(first_seen_candidates) if first_seen_candidates else 0
    representative["latest_seen_episode_no"] = latest_seen_episode_no
    representative["evidence_episode_nos"] = evidence_episode_nos[:120]
    representative["distinct_episode_count"] = distinct_episode_count
    representative["work_protagonist_evidence"] = {
        "episode_count": _bounded_episode_count_sum(
            evidence_rows,
            lambda row: dict(row.get("work_protagonist_evidence") or {}).get("episode_count"),
            total_episodes=total_episodes,
        )
    }
    representative["episode_focal_evidence"] = {
        "episode_count": _bounded_episode_count_sum(
            evidence_rows,
            lambda row: dict(row.get("episode_focal_evidence") or {}).get("episode_count"),
            total_episodes=total_episodes,
        )
    }
    representative["first_person_evidence"] = {
        "episode_count": _bounded_episode_count_sum(
            evidence_rows,
            lambda row: dict(row.get("first_person_evidence") or {}).get("episode_count"),
            total_episodes=total_episodes,
        )
    }
    representative["episode_role_counts"] = role_counts
    representative["voice_mode_counts"] = voice_counts
    representative["scene_weight_counts"] = scene_counts
    representative["relation_episode_count"] = _bounded_episode_count_sum(
        evidence_rows,
        lambda row: row.get("relation_episode_count"),
        total_episodes=total_episodes,
    )
    protagonist_evidence = dict(representative.get("protagonist_evidence") or {})
    protagonist_evidence["score"] = max(
        float(protagonist_evidence.get("score") or 0),
        _score_compacted_work_protagonist_candidate(representative, total_episodes=total_episodes),
    )
    protagonist_evidence["rank"] = min(int(dict(row.get("protagonist_evidence") or {}).get("rank") or 9999) for row in rows)
    representative["protagonist_evidence"] = protagonist_evidence
    representative["duplicate_compaction"] = {
        "row_count": len(rows),
        "evidence_row_count": len(evidence_rows),
        "compacted_keys": [str(row.get("canonical_character_key") or "") for row in rows],
        "ignored_cross_alias_keys": ignored_cross_alias_keys,
        "removed_cross_candidate_aliases": removed_cross_candidate_aliases,
    }
    return representative


def _compact_work_protagonist_duplicate_display_rows(
    rows: list[dict[str, object]],
    *,
    total_episodes: int,
) -> list[dict[str, object]]:
    rows_by_display: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        display_label = normalize_signal_entity_label(str(row.get("display_name") or ""))
        if display_label:
            rows_by_display.setdefault(display_label, []).append(row)

    duplicate_display_labels = {
        display_label
        for display_label, display_rows in rows_by_display.items()
        if len(display_rows) > 1 and any(_has_duplicate_canonical_key_conflict(row) for row in display_rows)
    }
    if not duplicate_display_labels:
        return rows

    compacted_rows: list[dict[str, object]] = []
    emitted_duplicate_labels: set[str] = set()
    all_display_labels = set(rows_by_display)
    for row in rows:
        display_label = normalize_signal_entity_label(str(row.get("display_name") or ""))
        if display_label not in duplicate_display_labels:
            compacted_rows.append(row)
            continue
        if display_label in emitted_duplicate_labels:
            continue
        emitted_duplicate_labels.add(display_label)
        compacted_rows.append(
            _build_compacted_work_protagonist_duplicate_row(
                rows_by_display[display_label],
                total_episodes=total_episodes,
                other_display_labels=all_display_labels - {display_label},
            )
        )
    return compacted_rows


def build_work_protagonist_resolution_input(
    rows: list[dict[str, object]],
    *,
    product_id: int | None = None,
    product_title: str = "",
    total_signal_episodes: int | None = None,
    max_candidates: int = 8,
) -> dict[str, object]:
    total_episodes = max(int(total_signal_episodes or 0), 1)

    def candidate_sort_key(row: dict[str, object]) -> tuple[int, float, int, int, str]:
        protagonist_evidence = dict(row.get("protagonist_evidence") or {})
        rank = int(protagonist_evidence.get("rank") or 9999)
        score = float(protagonist_evidence.get("score") or 0)
        role_counts = dict(row.get("episode_role_counts") or {})
        return (
            rank,
            -score,
            -int(row.get("distinct_episode_count") or 0),
            -int(role_counts.get("lead") or 0),
            str(row.get("display_name") or ""),
        )

    def compacted_candidate_sort_key(row: dict[str, object]) -> tuple[float, int, int, int, str]:
        protagonist_evidence = dict(row.get("protagonist_evidence") or {})
        score = float(protagonist_evidence.get("score") or 0)
        role_counts = dict(row.get("episode_role_counts") or {})
        work_protagonist_count = int(dict(row.get("work_protagonist_evidence") or {}).get("episode_count") or 0)
        focal_count = int(dict(row.get("episode_focal_evidence") or {}).get("episode_count") or 0)
        return (
            -score,
            -work_protagonist_count,
            -focal_count,
            -int(role_counts.get("lead") or 0),
            str(row.get("display_name") or ""),
        )

    candidate_rows = [
        row
        for row in sorted(rows, key=candidate_sort_key)
        if int(row.get("distinct_episode_count") or 0) > 0
        and str(row.get("entity_kind") or "person").strip().lower() in {"person", "stable_role"}
    ]
    candidate_rows = _compact_work_protagonist_duplicate_display_rows(
        candidate_rows,
        total_episodes=total_episodes,
    )
    candidate_rows = sorted(candidate_rows, key=compacted_candidate_sort_key)[: max(max_candidates, 1)]

    candidates: list[dict[str, object]] = []
    for row in candidate_rows:
        voice_counts = dict(row.get("voice_mode_counts") or {})
        scene_counts = dict(row.get("scene_weight_counts") or {})
        role_counts = dict(row.get("episode_role_counts") or {})
        protagonist_evidence = dict(row.get("protagonist_evidence") or {})
        episode_nos = [int(no) for no in list(row.get("evidence_episode_nos") or []) if int(no or 0) > 0]
        candidates.append(
            {
                "canonical_character_key": str(row.get("canonical_character_key") or ""),
                "display_name": str(row.get("display_name") or ""),
                "aliases": list(row.get("aliases") or [])[:8],
                "selection_eligible": _work_protagonist_resolution_candidate_is_selectable(row),
                "identity_status": str(row.get("identity_status") or ""),
                "identity_conflict_reasons": list(row.get("identity_conflict_reasons") or []),
                "display_safety": dict(row.get("display_safety") or build_inventory_display_safety(row)),
                "display_name_type": str(row.get("display_name_type") or ""),
                "entity_kind": str(row.get("entity_kind") or "person"),
                "distinct_episode_count": int(row.get("distinct_episode_count") or 0),
                "coverage_ratio": round(min(int(row.get("distinct_episode_count") or 0) / total_episodes, 1.0), 4),
                "first_seen_episode_no": int(row.get("first_seen_episode_no") or 0),
                "latest_seen_episode_no": int(row.get("latest_seen_episode_no") or 0),
                "evidence_episode_nos_sample": episode_nos[:8],
                "protagonist_rank": int(protagonist_evidence.get("rank") or 9999),
                "protagonist_score": float(protagonist_evidence.get("score") or 0),
                "work_protagonist_hint_count": int(dict(row.get("work_protagonist_evidence") or {}).get("episode_count") or 0),
                "episode_focal_count": int(dict(row.get("episode_focal_evidence") or {}).get("episode_count") or 0),
                "first_person_count": int(dict(row.get("first_person_evidence") or {}).get("episode_count") or 0),
                "lead_count": int(role_counts.get("lead") or 0),
                "high_scene_count": int(scene_counts.get("high") or 0),
                "voice_count": int(voice_counts.get("dialogue") or 0) + int(voice_counts.get("monologue") or 0),
                "relation_episode_count": int(row.get("relation_episode_count") or 0),
                "narration_names": list(row.get("narration_names") or [])[:8],
                "social_call_names": list(row.get("social_call_names") or [])[:8],
                "persona_names": list(row.get("persona_names") or [])[:8],
                "real_names": list(row.get("real_names") or [])[:8],
                "dominant_action_tags": list(row.get("dominant_action_tags") or [])[:5],
                "dominant_affect_tags": list(row.get("dominant_affect_tags") or [])[:5],
                "review_reasons": list(row.get("review_reasons") or []),
                "duplicate_compaction": dict(row.get("duplicate_compaction") or {}),
            }
        )

    episode_nos = sorted(
        {
            int(no)
            for row in rows
            for no in list(row.get("evidence_episode_nos") or [])
            if int(no or 0) > 0
        }
    )
    return {
        "schema_version": WORK_PROTAGONIST_RESOLUTION_FORMAT_VERSION,
        "product_id": product_id,
        "product_title": product_title,
        "total_signal_episodes": total_episodes,
        "episode_span": {
            "first": episode_nos[0] if episode_nos else 0,
            "latest": episode_nos[-1] if episode_nos else 0,
        },
        "candidates": candidates,
        "hard_rules": {
            "max_work_protagonists": 3,
            "co_main_protagonists_allowed": True,
            "do_not_merge_characters": True,
            "unresolved_is_allowed": True,
            "episode_work_protagonist_is_weak_hint": True,
        },
    }


def build_work_protagonist_resolution_user_prompt(
    resolver_input: dict[str, object],
    *,
    episode_summary_evidence: list[dict[str, object]] | None = None,
) -> str:
    bounded_evidence = list(episode_summary_evidence or [])[:20]
    return (
        "아래 JSON은 character_inventory_v3 cluster 결과에서 만든 작품 단위 주인공 판정 입력이다.\n"
        "후보 중 1~3명을 선택하거나, 확정할 수 없으면 UNRESOLVED를 반환하라.\n"
        "후보 병합, 새 후보 생성, 후보 이름 변경은 금지한다.\n\n"
        "resolver_input:\n"
        f"{json.dumps(resolver_input, ensure_ascii=False, sort_keys=True)}\n\n"
        "episode_summary_evidence:\n"
        f"{json.dumps(bounded_evidence, ensure_ascii=False, sort_keys=True)}"
    )


async def request_work_protagonist_resolution_payload(
    client: AsyncClient,
    *,
    resolver_input: dict[str, object],
    episode_summary_evidence: list[dict[str, object]] | None = None,
) -> dict | None:
    user_prompt = build_work_protagonist_resolution_user_prompt(
        resolver_input,
        episode_summary_evidence=episode_summary_evidence,
    )
    user_prompt = (
        f"{user_prompt}\n\nschema_parameters:\n"
        f"{json.dumps(WORK_PROTAGONIST_RESOLUTION_TOOL_SCHEMA.get('input_schema') or {}, ensure_ascii=False)}"
    )
    if OPENROUTER_API_KEY and EPISODE_CHARACTER_SIGNALS_OPENROUTER_MODEL:
        return await request_rp_openrouter_json_payload(
            client,
            system_prompt=WORK_PROTAGONIST_RESOLUTION_PROMPT,
            user_prompt=user_prompt,
            max_tokens=WORK_PROTAGONIST_RESOLUTION_MAX_OUTPUT_TOKENS,
            title="LikeNovel Story Agent Work Protagonist Resolution",
            model=require_paid_character_signals_openrouter_model(),
        )
    return None


def is_work_protagonist_resolution_provider_configured() -> bool:
    return bool(OPENROUTER_API_KEY and EPISODE_CHARACTER_SIGNALS_OPENROUTER_MODEL)


def _work_protagonist_score(row: dict[str, object]) -> float:
    return float(dict(row.get("protagonist_evidence") or {}).get("score") or 0)


def _work_protagonist_hint_count(row: dict[str, object]) -> int:
    return int(dict(row.get("work_protagonist_evidence") or {}).get("episode_count") or 0)


def _work_protagonist_focal_count(row: dict[str, object]) -> int:
    return int(dict(row.get("episode_focal_evidence") or {}).get("episode_count") or 0)


def _expand_near_tie_work_protagonist_keys(
    rows: list[dict[str, object]],
    selected_keys: list[str],
    *,
    excluded_keys: set[str] | None = None,
) -> list[str]:
    if len(selected_keys) != 1:
        return selected_keys[:WORK_PROTAGONIST_CO_MAIN_MAX_COUNT]

    excluded_key_set = {str(key) for key in (excluded_keys or set()) if str(key)}
    selected_key = selected_keys[0]
    selected_row = next((row for row in rows if str(row.get("canonical_character_key") or "") == selected_key), None)
    if selected_row is None:
        return selected_keys

    selected_score = _work_protagonist_score(selected_row)
    if selected_score < WORK_PROTAGONIST_CO_MAIN_MIN_SCORE:
        return selected_keys

    selected_work_count = _work_protagonist_hint_count(selected_row)
    selected_focal_count = _work_protagonist_focal_count(selected_row)
    if selected_work_count < 2 or selected_focal_count < 2:
        return selected_keys

    near_tie_rows = [
        row
        for row in rows
        if _work_protagonist_resolution_candidate_is_selectable(row)
        and str(row.get("canonical_character_key") or "") not in excluded_key_set
        and _work_protagonist_score(row) >= selected_score * WORK_PROTAGONIST_CO_MAIN_NEAR_TIE_SCORE_RATIO
        and _work_protagonist_hint_count(row) >= max(2, int(selected_work_count * WORK_PROTAGONIST_CO_MAIN_HINT_RATIO))
        and _work_protagonist_focal_count(row) >= max(2, int(selected_focal_count * WORK_PROTAGONIST_CO_MAIN_HINT_RATIO))
    ]
    if len(near_tie_rows) <= 1:
        return selected_keys

    near_tie_rows = sorted(
        near_tie_rows,
        key=lambda row: (
            -_work_protagonist_score(row),
            -_work_protagonist_hint_count(row),
            -_work_protagonist_focal_count(row),
            str(row.get("display_name") or ""),
        ),
    )[:WORK_PROTAGONIST_CO_MAIN_MAX_COUNT]
    return [str(row.get("canonical_character_key") or "") for row in near_tie_rows if str(row.get("canonical_character_key") or "")]


def _infer_near_tie_work_protagonist_keys(
    rows: list[dict[str, object]],
    *,
    excluded_keys: set[str] | None = None,
) -> list[str]:
    excluded_key_set = {str(key) for key in (excluded_keys or set()) if str(key)}
    selectable_rows = [
        row
        for row in rows
        if _work_protagonist_resolution_candidate_is_selectable(row)
        and str(row.get("canonical_character_key") or "") not in excluded_key_set
        and _work_protagonist_score(row) >= WORK_PROTAGONIST_CO_MAIN_MIN_SCORE
        and _work_protagonist_hint_count(row) >= 2
        and _work_protagonist_focal_count(row) >= 2
    ]
    if not selectable_rows:
        return []
    top_row = sorted(
        selectable_rows,
        key=lambda row: (
            -_work_protagonist_score(row),
            -_work_protagonist_hint_count(row),
            -_work_protagonist_focal_count(row),
            str(row.get("display_name") or ""),
        ),
    )[0]
    near_tie_keys = _expand_near_tie_work_protagonist_keys(
        rows,
        [str(top_row.get("canonical_character_key") or "")],
        excluded_keys=excluded_key_set,
    )
    return near_tie_keys if len(near_tie_keys) >= 2 else []


def validate_work_protagonist_resolution_payload(
    payload: dict | None,
    rows: list[dict[str, object]],
) -> dict[str, object]:
    row_by_key = {str(row.get("canonical_character_key") or ""): row for row in rows}
    unresolved = {
        "schema_version": WORK_PROTAGONIST_RESOLUTION_FORMAT_VERSION,
        "decision": "UNRESOLVED",
        "work_protagonist_key": None,
        "work_protagonist_keys": [],
        "confidence": "low",
        "reason_code": "invalid_payload",
        "rationale": "",
        "rejected": [],
        "safety_flags": {
            "requires_identity_merge": False,
            "selected_candidate_eligible": False,
            "multiple_plausible_main_candidates": False,
        },
    }
    if not isinstance(payload, dict):
        return unresolved

    decision = str(payload.get("decision") or payload.get("status") or "").strip().upper()
    confidence = str(payload.get("confidence") or "low").strip().lower()
    safety_flags = dict(payload.get("safety_flags") or {})
    reason_code = str(payload.get("reason_code") or "").strip() or "unspecified"
    rejected_keys = {
        str(item.get("key") or "").strip()
        for item in list(payload.get("rejected") or [])
        if isinstance(item, dict) and str(item.get("key") or "").strip()
    }
    normalized = {
        **unresolved,
        "decision": "UNRESOLVED",
        "confidence": confidence if confidence in {"high", "medium", "low"} else "low",
        "reason_code": reason_code,
        "rationale": str(payload.get("rationale") or payload.get("reason") or "")[:240],
        "rejected": list(payload.get("rejected") or [])[:8],
        "safety_flags": {
            "requires_identity_merge": bool(safety_flags.get("requires_identity_merge")),
            "selected_candidate_eligible": bool(safety_flags.get("selected_candidate_eligible")),
            "multiple_plausible_main_candidates": bool(safety_flags.get("multiple_plausible_main_candidates")),
        },
    }
    if decision != "RESOLVED":
        if reason_code == "ambiguous_dual_lead":
            near_tie_keys = _infer_near_tie_work_protagonist_keys(rows, excluded_keys=rejected_keys)
            if near_tie_keys:
                normalized["decision"] = "RESOLVED"
                normalized["work_protagonist_key"] = near_tie_keys[0]
                normalized["work_protagonist_keys"] = near_tie_keys
                normalized["confidence"] = "medium"
                normalized["reason_code"] = "co_main_protagonists"
                normalized["safety_flags"]["selected_candidate_eligible"] = True
                normalized["safety_flags"]["multiple_plausible_main_candidates"] = False
                return normalized
        normalized["reason_code"] = reason_code if reason_code != "unspecified" else "unresolved"
        return normalized
    if normalized["confidence"] not in {"high", "medium"}:
        normalized["reason_code"] = "low_confidence"
        return normalized
    if bool(safety_flags.get("requires_identity_merge")):
        normalized["reason_code"] = "requires_identity_merge"
        return normalized

    selected_keys: list[str] = []
    first_key = str(payload.get("work_protagonist_key") or payload.get("main_character_key") or "").strip()
    if first_key:
        selected_keys.append(first_key)
    for key in list(payload.get("work_protagonist_keys") or []):
        key_text = str(key or "").strip()
        if key_text and key_text not in selected_keys:
            selected_keys.append(key_text)

    if not selected_keys:
        normalized["reason_code"] = "selected_candidate_not_found"
        return normalized
    if len(selected_keys) > 3:
        normalized["reason_code"] = "too_many_work_protagonists"
        return normalized
    selected_keys = _expand_near_tie_work_protagonist_keys(rows, selected_keys, excluded_keys=rejected_keys)
    if bool(safety_flags.get("multiple_plausible_main_candidates")) and len(selected_keys) == 1:
        normalized["reason_code"] = "multiple_plausible_main_candidates"
        return normalized

    selected_rows = [row_by_key.get(selected_key) for selected_key in selected_keys]
    if any(row is None for row in selected_rows):
        normalized["reason_code"] = "selected_candidate_not_found"
        return normalized
    if any(not _work_protagonist_resolution_candidate_is_selectable(row or {}) for row in selected_rows):
        normalized["reason_code"] = "selected_candidate_not_eligible"
        return normalized
    if "selected_candidate_eligible" in safety_flags and not bool(safety_flags.get("selected_candidate_eligible")):
        normalized["reason_code"] = "selected_candidate_marked_ineligible"
        return normalized

    normalized["decision"] = "RESOLVED"
    normalized["work_protagonist_key"] = selected_keys[0]
    normalized["work_protagonist_keys"] = selected_keys
    normalized["reason_code"] = "co_main_protagonists" if len(selected_keys) > 1 else reason_code
    normalized["safety_flags"]["selected_candidate_eligible"] = True
    return normalized


def _apply_work_protagonist_resolution(
    rows: list[dict[str, object]],
    protagonist_resolution: dict[str, object],
) -> dict[str, object]:
    resolution = validate_work_protagonist_resolution_payload(protagonist_resolution, rows)
    selected_keys = (
        set(str(key) for key in list(resolution.get("work_protagonist_keys") or []) if str(key))
        if resolution.get("decision") == "RESOLVED"
        else set()
    )
    for row in rows:
        if str(row.get("work_role") or "") == "main_protagonist":
            row["work_role"] = "major_character" if int(row.get("distinct_episode_count") or 0) >= 1 else "unknown"
            row["role_confidence"] = "medium" if str(row.get("work_role") or "") == "major_character" else "low"
        if str(row.get("canonical_character_key") or "") in selected_keys:
            row["work_role"] = "main_protagonist"
            row["role_confidence"] = "high"
            row["classification_status"] = "AUTO_RESOLVED"
            row["review_reasons"] = []
            row["work_protagonist_resolution"] = resolution
        elif resolution.get("decision") != "RESOLVED" and int(dict(row.get("protagonist_evidence") or {}).get("rank") or 9999) <= 2:
            row["review_reasons"] = sorted(set(list(row.get("review_reasons") or []) + ["WORK_PROTAGONIST_UNRESOLVED"]))
            row["work_protagonist_resolution"] = resolution
    return resolution


def _work_protagonist_identity_scope_keys(row: dict[str, object]) -> set[str]:
    keys = {
        str(row.get("canonical_character_key") or "").strip(),
        str(row.get("identity_group_key") or "").strip(),
        *[
            str(value or "").strip()
            for value in list(row.get("protagonist_identity_scope_keys") or [])
        ],
        *[
            str(item.get("scope_key") or "").strip()
            for item in list(row.get("identity_group_members") or [])
            if isinstance(item, dict)
        ],
    }
    return {key for key in keys if key}


def _work_protagonist_source_keys(row: dict[str, object]) -> set[str]:
    return {
        key
        for key in [
            str(value or "").strip()
            for value in list(row.get("source_character_keys") or [])
        ]
        if key and not _is_generic_protagonist_source_key(key)
    }


def _work_protagonist_rows_share_identity(
    locked_row: dict[str, object],
    candidate_row: dict[str, object],
    *,
    allow_source_overlap: bool = False,
) -> bool:
    if _inventory_identity_blocking_conflict_reasons(candidate_row):
        return False
    if (
        _work_protagonist_identity_scope_keys(locked_row)
        & _work_protagonist_identity_scope_keys(candidate_row)
    ):
        return True
    return allow_source_overlap and bool(
        _work_protagonist_source_keys(locked_row)
        & _work_protagonist_source_keys(candidate_row)
    )


def _locked_work_protagonist_candidate_rank(
    locked_row: dict[str, object],
    candidate_row: dict[str, object],
) -> tuple[int, int, int, int, str]:
    locked_key = str(locked_row.get("canonical_character_key") or "").strip()
    candidate_key = str(candidate_row.get("canonical_character_key") or "").strip()
    identity_overlap = len(
        _work_protagonist_identity_scope_keys(locked_row)
        & _work_protagonist_identity_scope_keys(candidate_row)
    )
    source_overlap = len(_work_protagonist_source_keys(locked_row) & _work_protagonist_source_keys(candidate_row))
    return (
        0 if locked_key and candidate_key == locked_key else 1,
        -identity_overlap,
        -source_overlap,
        -int(candidate_row.get("distinct_episode_count") or 0),
        candidate_key,
    )


def _apply_locked_work_protagonist_rows(
    rows: list[dict[str, object]],
    locked_protagonist_rows: list[dict[str, object]],
) -> set[str]:
    locked_rows = [
        row
        for row in locked_protagonist_rows
        if str(row.get("work_role") or "") == "main_protagonist"
        and str(row.get("canonical_character_key") or "").strip()
    ]
    if not locked_rows:
        return set()

    resolved_main_candidate_ids = {
        id(row)
        for row in rows
        if str(row.get("work_role") or "") == "main_protagonist"
    }
    for row in rows:
        if str(row.get("work_role") or "") != "main_protagonist":
            continue
        row["work_role"] = "major_character" if int(row.get("distinct_episode_count") or 0) >= 1 else "unknown"
        row["role_confidence"] = "medium" if str(row.get("work_role") or "") == "major_character" else "low"

    matched_scope_keys: set[str] = set()
    used_candidate_ids: set[int] = set()
    for locked_row in locked_rows:
        candidates = [
            row
            for row in rows
            if id(row) not in used_candidate_ids
            and _work_protagonist_rows_share_identity(
                locked_row,
                row,
                allow_source_overlap=id(row) in resolved_main_candidate_ids,
            )
        ]
        if not candidates:
            continue
        selected_row = min(
            candidates,
            key=lambda row: (
                0 if id(row) in resolved_main_candidate_ids else 1,
                *_locked_work_protagonist_candidate_rank(locked_row, row),
            ),
        )
        used_candidate_ids.add(id(selected_row))

        locked_scope_key = str(locked_row.get("canonical_character_key") or "").strip()
        selected_scope_key = str(selected_row.get("canonical_character_key") or "").strip()
        identity_scope_keys = list(
            dict.fromkeys(
                [
                    *[
                        str(value or "").strip()
                        for value in list(locked_row.get("protagonist_identity_scope_keys") or [])
                    ],
                    locked_scope_key,
                    selected_scope_key,
                ]
            )
        )
        selected_row["work_role"] = "main_protagonist"
        selected_row["role_confidence"] = "high"
        selected_row["classification_status"] = "AUTO_RESOLVED"
        selected_row["review_reasons"] = []
        selected_row["identity_group_key"] = str(
            locked_row.get("identity_group_key") or locked_scope_key
        ).strip()
        selected_row["identity_group_role"] = "current_protagonist"
        selected_row["protagonist_identity_scope_keys"] = [key for key in identity_scope_keys if key]
        selected_row["is_protagonist_identity_member"] = True
        if isinstance(locked_row.get("identity_group_members"), list):
            selected_row["identity_group_members"] = list(locked_row.get("identity_group_members") or [])
        if isinstance(locked_row.get("work_protagonist_resolution"), dict):
            selected_row["work_protagonist_resolution"] = dict(
                locked_row.get("work_protagonist_resolution") or {}
            )
        matched_scope_keys.add(locked_scope_key)
    return matched_scope_keys


def _row_episode_count(row: dict[str, object], field_name: str) -> int:
    return int(dict(row.get(field_name) or {}).get("episode_count") or 0)


def _is_previous_protagonist_identity_candidate(
    row: dict[str, object],
    *,
    main_row: dict[str, object],
) -> bool:
    if row is main_row:
        return False
    if str(row.get("work_role") or "") == "main_protagonist":
        return False
    if str(row.get("entity_kind") or "person").strip().lower() not in {"person", "stable_role"}:
        return False
    if _inventory_identity_blocking_conflict_reasons(row):
        return False
    if str(build_inventory_display_safety(row).get("status") or "") != "pass":
        return False

    first_person_count = _row_episode_count(row, "first_person_evidence")
    work_protagonist_count = _row_episode_count(row, "work_protagonist_evidence")
    focal_count = _row_episode_count(row, "episode_focal_evidence")
    if first_person_count <= 0 or work_protagonist_count <= 0 or focal_count <= 0:
        return False

    source_keys = [str(key or "").strip() for key in list(row.get("source_character_keys") or [])]
    if not any(_is_generic_protagonist_source_key(source_key) for source_key in source_keys):
        return False

    candidate_first = int(row.get("first_seen_episode_no") or 0)
    candidate_latest = int(row.get("latest_seen_episode_no") or 0)
    main_first = int(main_row.get("first_seen_episode_no") or 0)
    if candidate_first <= 0 or candidate_latest <= 0 or main_first <= 0:
        return False
    if candidate_first > main_first:
        return False
    if candidate_latest > main_first + 1:
        return False
    return True


def _identity_group_member_item(
    row: dict[str, object],
    *,
    role: str,
    link_type: str,
) -> dict[str, object]:
    return {
        "scope_key": str(row.get("canonical_character_key") or ""),
        "display_name": str(row.get("display_name") or ""),
        "role": role,
        "link_type": link_type,
        "evidence_episode_nos": list(row.get("evidence_episode_nos") or [])[:12],
    }


def _apply_protagonist_identity_groups(rows: list[dict[str, object]]) -> None:
    main_rows = [row for row in rows if str(row.get("work_role") or "") == "main_protagonist"]
    if len(main_rows) != 1:
        return
    main_row = main_rows[0]
    main_key = str(main_row.get("canonical_character_key") or "")
    if not main_key:
        return

    linked_rows = [
        row
        for row in rows
        if _is_previous_protagonist_identity_candidate(row, main_row=main_row)
    ]
    if not linked_rows:
        return
    linked_rows = sorted(
        linked_rows,
        key=lambda row: (
            -_row_episode_count(row, "first_person_evidence"),
            -_row_episode_count(row, "work_protagonist_evidence"),
            int(row.get("first_seen_episode_no") or 0),
            str(row.get("display_name") or ""),
        ),
    )[:3]

    identity_scope_keys = [main_key] + [
        str(row.get("canonical_character_key") or "")
        for row in linked_rows
        if str(row.get("canonical_character_key") or "")
    ]
    members = [
        _identity_group_member_item(
            main_row,
            role="current_protagonist",
            link_type="primary",
        ),
        *[
            _identity_group_member_item(
                row,
                role="previous_protagonist_identity",
                link_type="first_person_reincarnation_identity",
            )
            for row in linked_rows
        ],
    ]
    for row in [main_row, *linked_rows]:
        row["identity_group_key"] = main_key
        row["protagonist_identity_scope_keys"] = identity_scope_keys
        row["identity_group_members"] = members
        row["is_protagonist_identity_member"] = True
    main_row["identity_group_role"] = "current_protagonist"
    for row in linked_rows:
        row["identity_group_role"] = "previous_protagonist_identity"
        row["identity_linked_to_scope_key"] = main_key
        row["identity_link_type"] = "first_person_reincarnation_identity"


async def build_work_protagonist_resolution_for_inventory_v3(
    *,
    product_id: int,
    product_title: str,
    signal_rows: list[dict],
    summary_client: AsyncClient | None,
    episode_summary_rows: list[dict] | None = None,
    verbose: bool = False,
) -> dict[str, object] | None:
    if summary_client is None:
        if verbose:
            print(f"[work-protagonist-resolution-skip] product_id={product_id} reason=summary_client_missing")
        return None
    if not is_work_protagonist_resolution_provider_configured():
        if verbose:
            print(f"[work-protagonist-resolution-skip] product_id={product_id} reason=provider_missing")
        return None
    base_inventory_rows = aggregate_character_inventory_v3_rows(signal_rows)
    if not base_inventory_rows:
        return None
    total_signal_episodes = len(
        {
            int((extract_json_object(str(row.get("summary_text") or "")) or {}).get("episode_no") or row.get("episode_from") or 0)
            for row in signal_rows
            if int((extract_json_object(str(row.get("summary_text") or "")) or {}).get("episode_no") or row.get("episode_from") or 0) > 0
        }
    )
    resolver_input = build_work_protagonist_resolution_input(
        base_inventory_rows,
        product_id=product_id,
        product_title=product_title,
        total_signal_episodes=total_signal_episodes,
    )
    if not list(resolver_input.get("candidates") or []):
        return None
    episode_summary_evidence = build_work_protagonist_episode_summary_evidence(
        list(episode_summary_rows or []),
    )
    payload = await request_work_protagonist_resolution_payload(
        summary_client,
        resolver_input=resolver_input,
        episode_summary_evidence=episode_summary_evidence,
    )
    resolution = validate_work_protagonist_resolution_payload(payload, base_inventory_rows)
    if verbose:
        print(
            f"[work-protagonist-resolution] product_id={product_id} "
            f"decision={resolution.get('decision')} reason={resolution.get('reason_code')} "
            f"keys={len(list(resolution.get('work_protagonist_keys') or []))}"
        )
    return resolution


def _public_inventory_duplicate_rank(row: dict[str, object]) -> tuple[int, int, int, int, str]:
    voice_counts = dict(row.get("voice_mode_counts") or {})
    speaking_episode_count = int(voice_counts.get("dialogue") or 0) + int(voice_counts.get("monologue") or 0)
    return (
        0 if str(row.get("work_role") or "") == "main_protagonist" else 1,
        0 if not _inventory_identity_blocking_conflict_reasons(row) else 1,
        -int(row.get("distinct_episode_count") or 0),
        -speaking_episode_count,
        str(row.get("canonical_character_key") or ""),
    )


def _suppress_duplicate_public_display_rows(rows: list[dict[str, object]]) -> None:
    rows_by_display: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        if not bool(row.get("public_chat_eligible")):
            continue
        display_label = normalize_signal_entity_label(str(row.get("display_name") or ""))
        if not display_label:
            continue
        rows_by_display.setdefault(display_label, []).append(row)

    for duplicate_rows in rows_by_display.values():
        if len(duplicate_rows) <= 1:
            continue
        keep_row = sorted(duplicate_rows, key=_public_inventory_duplicate_rank)[0]
        for row in duplicate_rows:
            if row is keep_row:
                continue
            row["public_chat_eligible"] = False
            row["public_slot_eligible"] = False
            row["review_reasons"] = sorted(
                set(list(row.get("review_reasons") or []) + ["DUPLICATE_PUBLIC_DISPLAY_NAME"])
            )


def _suppress_main_alias_public_slot_rows(rows: list[dict[str, object]]) -> None:
    main_display_labels: set[str] = set()
    main_alias_labels: set[str] = set()
    for row in rows:
        if str(row.get("work_role") or "") != "main_protagonist":
            continue
        display_label = normalize_signal_entity_label(str(row.get("display_name") or ""))
        if display_label:
            main_display_labels.add(display_label)
        main_alias_labels.update(
            normalize_signal_entity_label(str(alias or ""))
            for alias in list(row.get("aliases") or [])
            if normalize_signal_entity_label(str(alias or ""))
        )

    if not main_alias_labels:
        return

    for row in rows:
        if str(row.get("work_role") or "") == "main_protagonist" or not bool(row.get("public_slot_eligible")):
            continue
        display_label = normalize_signal_entity_label(str(row.get("display_name") or ""))
        if not display_label or display_label in main_display_labels or display_label not in main_alias_labels:
            continue
        row["public_slot_eligible"] = False
        row["review_reasons"] = sorted(
            set(list(row.get("review_reasons") or []) + ["MAIN_ALIAS_PUBLIC_SLOT_DUPLICATE"])
        )


def _character_inventory_continuity_aliases(
    scope_key: str,
    payload: dict[str, object],
) -> set[str]:
    aliases = {
        str(value or "").strip()
        for field_name in (
            "source_character_keys",
            "protagonist_identity_scope_keys",
        )
        for value in list(payload.get(field_name) or [])
        if str(value or "").strip()
    }
    for field_name in ("identity_group_key", "identity_linked_to_scope_key"):
        value = str(payload.get(field_name) or "").strip()
        if value:
            aliases.add(value)
    if scope_key:
        aliases.add(scope_key)
    return aliases


def _remap_character_inventory_identity_references(
    row: dict[str, object],
    scope_key_map: dict[str, str],
) -> None:
    for field_name in ("identity_group_key", "identity_linked_to_scope_key"):
        value = str(row.get(field_name) or "").strip()
        if value in scope_key_map:
            row[field_name] = scope_key_map[value]
    for field_name in ("protagonist_identity_scope_keys",):
        if not isinstance(row.get(field_name), list):
            continue
        row[field_name] = list(
            dict.fromkeys(
                scope_key_map.get(str(value or "").strip(), str(value or "").strip())
                for value in list(row.get(field_name) or [])
                if str(value or "").strip()
            )
        )
    if isinstance(row.get("identity_group_members"), list):
        members: list[dict[str, object]] = []
        for raw_member in list(row.get("identity_group_members") or []):
            if not isinstance(raw_member, dict):
                continue
            member = dict(raw_member)
            member_scope_key = str(member.get("scope_key") or "").strip()
            if member_scope_key in scope_key_map:
                member["scope_key"] = scope_key_map[member_scope_key]
            members.append(member)
        row["identity_group_members"] = members


def _has_character_serving_contract(payload: dict[str, object] | None) -> bool:
    item = dict(payload or {})
    readiness = dict(item.get("chat_readiness_v1") or {})
    return bool(
        item.get("public_chat_eligible")
        or item.get("public_slot_eligible")
        or readiness.get("character_chat_allowed")
        or readiness.get("public_slot_allowed")
    )


def reconcile_character_inventory_v3_scope_keys(
    rows: list[dict[str, object]],
    *,
    old_inventory_map: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    reconciled_rows = [dict(row) for row in rows]
    old_rows = {
        str(scope_key or "").strip(): {
            **dict(payload or {}),
            "canonical_character_key": str(
                dict(payload or {}).get("canonical_character_key") or scope_key or ""
            ).strip(),
        }
        for scope_key, payload in (old_inventory_map or {}).items()
        if str(scope_key or "").strip()
    }
    if not old_rows or not reconciled_rows:
        return reconciled_rows

    old_alias_owners: dict[str, set[str]] = {}
    for old_scope_key, old_payload in old_rows.items():
        for alias_key in _character_inventory_continuity_aliases(
            old_scope_key,
            old_payload,
        ):
            old_alias_owners.setdefault(alias_key, set()).add(old_scope_key)

    new_alias_owners: dict[str, set[str]] = {}
    for row in reconciled_rows:
        generated_scope_key = str(row.get("canonical_character_key") or "").strip()
        for alias_key in _character_inventory_continuity_aliases(
            generated_scope_key,
            row,
        ):
            new_alias_owners.setdefault(alias_key, set()).add(generated_scope_key)

    claimed_old_scope_keys: set[str] = set()
    scope_key_map: dict[str, str] = {}
    for row in reconciled_rows:
        generated_scope_key = str(row.get("canonical_character_key") or "").strip()
        candidates: set[str] = set()
        if generated_scope_key in old_rows:
            candidates.add(generated_scope_key)
        else:
            for alias_key in _character_inventory_continuity_aliases(
                generated_scope_key,
                row,
            ):
                old_owners = old_alias_owners.get(alias_key, set())
                new_owners = new_alias_owners.get(alias_key, set())
                if len(old_owners) == 1 and len(new_owners) == 1:
                    candidates.update(old_owners)

        available_candidates = candidates - claimed_old_scope_keys
        if len(available_candidates) == 1:
            durable_scope_key = next(iter(available_candidates))
            claimed_old_scope_keys.add(durable_scope_key)
            scope_key_map[generated_scope_key] = durable_scope_key
            if durable_scope_key != generated_scope_key:
                old_payload = old_rows[durable_scope_key]
                legacy_scope_keys = sorted(
                    {
                        generated_scope_key,
                        *list(old_payload.get("legacy_scope_keys") or []),
                        *list(row.get("legacy_scope_keys") or []),
                    }
                    - {durable_scope_key, ""}
                )
                row["canonical_character_key"] = durable_scope_key
                row["durable_character_key"] = durable_scope_key
                row["legacy_scope_keys"] = legacy_scope_keys
                row["continuity_status"] = "reused"
                row["continuity_reason"] = "unique_identity_alias"
                row["continuity_version"] = 1
            continue

        normalized_display_name = normalize_signal_entity_label(
            str(row.get("display_name") or "")
        )
        same_name_old_scope_keys = {
            old_scope_key
            for old_scope_key, old_payload in old_rows.items()
            if old_scope_key not in claimed_old_scope_keys
            and normalized_display_name
            and normalize_signal_entity_label(
                str(old_payload.get("display_name") or "")
            )
            == normalized_display_name
        }
        if candidates or same_name_old_scope_keys:
            row["continuity_status"] = "ambiguous"
            row["continuity_reason"] = "non_unique_or_name_only"
            row["continuity_version"] = 1
            row["public_chat_eligible"] = False
            row["public_slot_eligible"] = False
            chat_readiness = dict(row.get("chat_readiness_v1") or {})
            chat_readiness["exposure_decision"] = "hold"
            chat_readiness["character_chat_allowed"] = False
            chat_readiness["public_slot_allowed"] = False
            row["chat_readiness_v1"] = chat_readiness
            row["identity_conflict_reasons"] = sorted(
                set(list(row.get("identity_conflict_reasons") or []))
                | {"identity_continuity_ambiguous"}
            )
            row["review_reasons"] = sorted(
                set(list(row.get("review_reasons") or []))
                | {"IDENTITY_CONTINUITY_AMBIGUOUS"}
            )

    for row in reconciled_rows:
        _remap_character_inventory_identity_references(row, scope_key_map)
    return reconciled_rows


def aggregate_character_inventory_v3_rows(
    signal_rows: list[dict],
    *,
    protagonist_resolution: dict | None = None,
    locked_protagonist_rows: list[dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    observations = build_character_inventory_v3_observations(signal_rows)
    clusters = resolve_character_inventory_v3_clusters(observations)
    total_signal_episodes = len(
        {
            int((extract_json_object(str(row.get("summary_text") or "")) or {}).get("episode_no") or row.get("episode_from") or 0)
            for row in signal_rows
            if int((extract_json_object(str(row.get("summary_text") or "")) or {}).get("episode_no") or row.get("episode_from") or 0) > 0
        }
    )
    rows: list[dict[str, object]] = []
    for cluster in clusters:
        cluster_observations = list(cluster.get("observations") or [])
        episode_nos = sorted(
            {
                int(observation.get("episode_no") or 0)
                for observation in cluster_observations
                if int(observation.get("episode_no") or 0) > 0
            }
        )
        aliases = sorted(
            {
                alias
                for observation in cluster_observations
                for alias in [
                    str(observation.get("display_name") or ""),
                    *list(observation.get("aliases") or []),
                    *list(observation.get("narration_names") or []),
                    *list(observation.get("social_call_names") or []),
                    *list(observation.get("persona_names") or []),
                    *list(observation.get("real_names") or []),
                ]
                if str(alias).strip()
            },
            key=lambda value: (0 if value == str(cluster.get("display_name") or "") else 1, -len(value), value),
        )
        narration_counts, narration_raw = _collect_cluster_name_signal_counts(cluster_observations, ("narration_names",))
        social_counts, social_raw = _collect_cluster_name_signal_counts(cluster_observations, ("social_call_names",))
        persona_counts, persona_raw = _collect_cluster_name_signal_counts(cluster_observations, ("persona_names",))
        real_counts, real_raw = _collect_cluster_name_signal_counts(cluster_observations, ("real_names",))
        sorted_name_signals = lambda counts, raw: [
            raw[normalized_label]
            for normalized_label, _ in sorted(counts.items(), key=lambda item: (-item[1], -len(item[0]), item[0]))
        ][:8]
        role_counts = {
            role: _episode_count(cluster_observations, lambda observation, role=role: str(observation.get("role_in_episode") or "") == role)
            for role in ["lead", "counterpart", "support", "obstacle"]
        }
        voice_counts = {
            mode: _episode_count(cluster_observations, lambda observation, mode=mode: str(observation.get("voice_mode") or "") == mode)
            for mode in ["dialogue", "monologue", "narration_only"]
        }
        scene_counts = {
            weight: _episode_count(cluster_observations, lambda observation, weight=weight: str(observation.get("scene_weight") or "") == weight)
            for weight in ["high", "medium", "low"]
        }
        relation_episode_count = _episode_count(cluster_observations, lambda observation: bool(list(observation.get("relation_edges") or [])))
        source_observation_refs = sorted(str(observation.get("observation_id") or "") for observation in cluster_observations)
        identity_status = str(cluster.get("identity_status") or "UNRESOLVED")
        identity_conflict_reasons = list(cluster.get("identity_conflict_reasons") or [])
        identity_confidence = (
            "high"
            if identity_status == "RESOLVED_NAMED" and len(cluster_observations) >= 2 and not identity_conflict_reasons
            else "medium"
            if identity_status in {"RESOLVED_NAMED", "RESOLVED_STABLE_ROLE"} and not identity_conflict_reasons
            else "low"
        )
        rows.append(
            {
                "schema_version": CHARACTER_INVENTORY_V3_FORMAT_VERSION,
                "canonical_character_key": str(cluster.get("canonical_character_key") or ""),
                "display_name": str(cluster.get("display_name") or ""),
                "display_name_source": str(cluster.get("display_name_source") or "identity_label"),
                "display_name_type": "generic" if is_generic_character_label(str(cluster.get("display_name") or "")) else "named",
                "is_generic_display_name": is_generic_character_label(str(cluster.get("display_name") or "")),
                "entity_kind": Counter(str(observation.get("entity_kind") or "person") for observation in cluster_observations).most_common(1)[0][0],
                "source_character_keys": list(cluster.get("source_character_keys") or []),
                "source_observation_refs": source_observation_refs,
                "preferred_legacy_character_key": (
                    str(list(cluster.get("source_character_keys") or [])[0])
                    if len(list(cluster.get("source_character_keys") or [])) == 1
                    else None
                ),
                "aliases": aliases[:8],
                "narration_names": sorted_name_signals(narration_counts, narration_raw),
                "social_call_names": sorted_name_signals(social_counts, social_raw),
                "persona_names": sorted_name_signals(persona_counts, persona_raw),
                "real_names": sorted_name_signals(real_counts, real_raw),
                "identity_status": identity_status,
                "identity_confidence": identity_confidence,
                "identity_conflict_reasons": identity_conflict_reasons,
                "first_seen_episode_no": episode_nos[0] if episode_nos else 0,
                "latest_seen_episode_no": episode_nos[-1] if episode_nos else 0,
                "evidence_episode_nos": episode_nos[:120],
                "distinct_episode_count": len(episode_nos),
                "raw_observation_count": len(cluster_observations),
                "episode_focal_evidence": {
                    "episode_count": _episode_count(cluster_observations, lambda observation: bool(observation.get("episode_focal"))),
                    "source_character_keys": sorted(
                        {
                            str(observation.get("source_character_key") or "")
                            for observation in cluster_observations
                            if bool(observation.get("episode_focal"))
                        }
                    ),
                },
                "work_protagonist_evidence": {
                    "episode_count": _episode_count(cluster_observations, lambda observation: bool(observation.get("work_protagonist"))),
                    "source_character_keys": sorted(
                        {
                            str(observation.get("source_character_key") or "")
                            for observation in cluster_observations
                            if bool(observation.get("work_protagonist"))
                        }
                    ),
                },
                "first_person_evidence": {
                    "episode_count": _episode_count(cluster_observations, lambda observation: bool(observation.get("first_person"))),
                },
                "episode_role_counts": role_counts,
                "voice_mode_counts": voice_counts,
                "scene_weight_counts": scene_counts,
                "relation_episode_count": relation_episode_count,
                "role_facets": sorted(
                    {
                        facet
                        for facet, enabled in [
                            ("work_protagonist", _episode_count(cluster_observations, lambda observation: bool(observation.get("work_protagonist"))) > 0),
                            ("episode_focal", _episode_count(cluster_observations, lambda observation: bool(observation.get("episode_focal"))) > 0),
                            ("first_person_narrator", _episode_count(cluster_observations, lambda observation: bool(observation.get("first_person"))) > 0),
                            ("counterpart", role_counts.get("counterpart", 0) > 0),
                            ("obstacle", role_counts.get("obstacle", 0) >= 2),
                        ]
                        if enabled
                    }
                ),
                "opposition_role": "rival_or_antagonist" if role_counts.get("obstacle", 0) >= 2 and relation_episode_count >= 2 else "unknown",
                "dominant_action_tags": [
                    key for key, _ in Counter(
                        tag
                        for observation in cluster_observations
                        for tag in list(observation.get("action_tags") or [])
                    ).most_common(5)
                ],
                "dominant_affect_tags": [
                    key for key, _ in Counter(
                        tag
                        for observation in cluster_observations
                        for tag in list(observation.get("affect_tags") or [])
                    ).most_common(5)
                ],
            }
        )
    _mark_unverified_first_person_identity_rows(rows)
    _classify_character_inventory_v3_rows(
        rows,
        total_signal_episodes,
        protagonist_resolution=protagonist_resolution,
        locked_protagonist_rows=locked_protagonist_rows,
    )
    _suppress_duplicate_public_display_rows(rows)
    _suppress_main_alias_public_slot_rows(rows)
    return sorted(
        rows,
        key=lambda item: (
            0 if str(item.get("work_role") or "") == "main_protagonist" else 1,
            int(dict(item.get("protagonist_evidence") or {}).get("rank") or 9999),
            -int(item.get("distinct_episode_count") or 0),
            str(item.get("display_name") or ""),
        ),
    )


def build_character_inventory_v3_hash_payload(item: dict[str, object]) -> dict[str, object]:
    payload: dict[str, object] = {
        "display_name": str(item.get("display_name") or ""),
        "display_name_source": str(item.get("display_name_source") or ""),
        "aliases": list(item.get("aliases") or []),
        "narration_names": list(item.get("narration_names") or []),
        "social_call_names": list(item.get("social_call_names") or []),
        "persona_names": list(item.get("persona_names") or []),
        "real_names": list(item.get("real_names") or []),
        "source_character_keys": list(item.get("source_character_keys") or []),
        "source_observation_refs": list(item.get("source_observation_refs") or []),
        "identity_status": str(item.get("identity_status") or ""),
        "identity_conflict_reasons": list(item.get("identity_conflict_reasons") or []),
        "entity_kind": str(item.get("entity_kind") or ""),
        "work_role": str(item.get("work_role") or ""),
        "role_confidence": str(item.get("role_confidence") or ""),
        "classification_status": str(item.get("classification_status") or ""),
        "review_reasons": list(item.get("review_reasons") or []),
        "is_protagonist": bool(item.get("is_protagonist")),
        "protagonist_confidence": str(item.get("protagonist_confidence") or ""),
        "protagonist_evidence": dict(item.get("protagonist_evidence") or {}),
        "work_protagonist_resolution": dict(item.get("work_protagonist_resolution") or {}),
        "rp_signal_quality": dict(item.get("rp_signal_quality") or {}),
        "display_safety": dict(item.get("display_safety") or {}),
        "public_chat_eligible": item.get("public_chat_eligible"),
        "public_slot_eligible": item.get("public_slot_eligible"),
        "identity_surface": dict(item.get("identity_surface") or {}),
        "reveal_boundary": dict(item.get("reveal_boundary") or {}),
        "read_range_state_snapshot": dict(item.get("read_range_state_snapshot") or {}),
        "interaction_affordance_v1": dict(item.get("interaction_affordance_v1") or {}),
        "adjacent_event_seed_v1": dict(item.get("adjacent_event_seed_v1") or {}),
        "pov_and_protagonist_centrality_v1": dict(item.get("pov_and_protagonist_centrality_v1") or {}),
        "voice_contract_v1": dict(item.get("voice_contract_v1") or {}),
        "chat_readiness_v1": dict(item.get("chat_readiness_v1") or {}),
        "evidence_episode_nos": list(item.get("evidence_episode_nos") or []),
    }
    optional_identity_fields = {
        "identity_group_key": str(item.get("identity_group_key") or ""),
        "identity_group_role": str(item.get("identity_group_role") or ""),
        "identity_linked_to_scope_key": str(item.get("identity_linked_to_scope_key") or ""),
        "identity_link_type": str(item.get("identity_link_type") or ""),
        "protagonist_identity_scope_keys": list(item.get("protagonist_identity_scope_keys") or []),
        "identity_group_members": list(item.get("identity_group_members") or []),
        "is_protagonist_identity_member": bool(item.get("is_protagonist_identity_member")),
    }
    payload.update(
        {
            key: value
            for key, value in optional_identity_fields.items()
            if value not in ("", [], False)
        }
    )
    return payload


def build_character_inventory_v3_source_hash(item: dict[str, object]) -> str:
    return build_compound_summary_source_hash(
        CHARACTER_INVENTORY_V3_FORMAT_VERSION,
        [
            str(item.get("canonical_character_key") or ""),
            json.dumps(
                build_character_inventory_v3_hash_payload(item),
                ensure_ascii=False,
                sort_keys=True,
            ),
        ],
    )


def upsert_character_inventory_v3_item(cur, *, product_id: int, item: dict[str, object]) -> bool:
    scope_key = str(item.get("canonical_character_key") or "").strip()
    if not scope_key:
        return False
    _, inserted = upsert_summary(
        cur=cur,
        product_id=product_id,
        summary_type="character_inventory_v3",
        scope_key=scope_key,
        source_hash=build_character_inventory_v3_source_hash(item),
        source_doc_count=max(int(item.get("distinct_episode_count") or 0), 1),
        episode_from=int(item.get("first_seen_episode_no") or 0) or None,
        episode_to=int(item.get("latest_seen_episode_no") or 0) or None,
        summary_text=json.dumps(item, ensure_ascii=False),
    )
    return inserted


def build_character_inventory_v3_summaries_from_signal_rows(
    cur,
    *,
    product_id: int,
    signal_rows: list[dict],
    protagonist_resolution: dict | None = None,
) -> tuple[int, int]:
    old_inventory_map = fetch_active_character_inventory_map(
        cur=cur,
        product_id=product_id,
        summary_type="character_inventory_v3",
    )
    locked_protagonist_rows: list[dict[str, object]] = []
    for scope_key, payload in old_inventory_map.items():
        if str(payload.get("work_role") or "") != "main_protagonist":
            continue
        locked_row = dict(payload)
        locked_row.setdefault("canonical_character_key", scope_key)
        locked_protagonist_rows.append(locked_row)
    locked_protagonist_by_scope = {
        str(row.get("canonical_character_key") or "").strip(): row
        for row in locked_protagonist_rows
        if str(row.get("canonical_character_key") or "").strip()
    }

    inventory_rows = aggregate_character_inventory_v3_rows(
        signal_rows,
        protagonist_resolution=protagonist_resolution,
        locked_protagonist_rows=locked_protagonist_rows,
    )
    inventory_rows = reconcile_character_inventory_v3_scope_keys(
        inventory_rows,
        old_inventory_map=old_inventory_map,
    )
    if signal_rows and not inventory_rows and not locked_protagonist_rows:
        raise ValueError(f"character_inventory_v3 aggregation returned 0 rows despite active signals: product_id={product_id}")

    inserted_count = 0
    reused_count = 0
    valid_scope_keys: set[str] = set()
    preserved_locked_scope_keys: set[str] = set()
    for item in inventory_rows:
        scope_key = str(item.get("canonical_character_key") or "").strip()
        if not scope_key:
            continue
        old_item = dict(old_inventory_map.get(scope_key) or {})
        if _has_character_serving_contract(old_item) and not _has_character_serving_contract(item):
            valid_scope_keys.add(scope_key)
            reused_count += 1
            logger.warning(
                "story_agent_character_lkg_preserved product_id=%s scope_key=%s reason=current_inventory_not_service_eligible",
                product_id,
                scope_key,
            )
            continue
        if scope_key in locked_protagonist_by_scope and _inventory_identity_blocking_conflict_reasons(item):
            valid_scope_keys.add(scope_key)
            preserved_locked_scope_keys.add(scope_key)
            reused_count += 1
            logger.warning(
                "story_agent_protagonist_lock_preserved product_id=%s scope_key=%s reason=identity_conflict_in_current_inventory",
                product_id,
                scope_key,
            )
            continue
        valid_scope_keys.add(scope_key)
        inserted = upsert_character_inventory_v3_item(cur, product_id=product_id, item=item)
        if inserted:
            inserted_count += 1
        else:
            reused_count += 1

    for locked_row in locked_protagonist_rows:
        locked_scope_key = str(locked_row.get("canonical_character_key") or "").strip()
        if not locked_scope_key:
            continue
        if locked_scope_key in preserved_locked_scope_keys:
            continue
        if any(
            str(item.get("work_role") or "") == "main_protagonist"
            and _work_protagonist_rows_share_identity(locked_row, item)
            for item in inventory_rows
        ):
            continue
        valid_scope_keys.add(locked_scope_key)
        reused_count += 1
        logger.warning(
            "story_agent_protagonist_lock_preserved product_id=%s scope_key=%s reason=identity_not_in_current_inventory",
            product_id,
            locked_scope_key,
        )

    for old_scope_key, old_item in old_inventory_map.items():
        normalized_old_scope_key = str(old_scope_key or "").strip()
        if (
            not normalized_old_scope_key
            or normalized_old_scope_key in valid_scope_keys
            or not _has_character_serving_contract(old_item)
        ):
            continue
        valid_scope_keys.add(normalized_old_scope_key)
        reused_count += 1
        logger.warning(
            "story_agent_character_lkg_preserved product_id=%s scope_key=%s reason=missing_from_current_inventory",
            product_id,
            normalized_old_scope_key,
        )

    deactivate_missing_active_scopes(cur, product_id, "character_inventory_v3", valid_scope_keys)
    return inserted_count, reused_count


def build_character_inventory_v3_summaries(
    cur,
    *,
    product_id: int,
    protagonist_resolution: dict | None = None,
) -> tuple[int, int]:
    signal_rows = fetch_active_summary_rows(cur=cur, product_id=product_id, summary_type="episode_character_signals")
    return build_character_inventory_v3_summaries_from_signal_rows(
        cur,
        product_id=product_id,
        signal_rows=signal_rows,
        protagonist_resolution=protagonist_resolution,
    )


async def build_character_inventory_v3_summaries_resolved(
    cur,
    *,
    product_id: int,
    product_title: str = "",
    summary_client: AsyncClient | None = None,
    episode_summary_rows: list[dict] | None = None,
    verbose: bool = False,
) -> tuple[int, int]:
    signal_rows = fetch_active_summary_rows(cur=cur, product_id=product_id, summary_type="episode_character_signals")
    protagonist_resolution = await build_work_protagonist_resolution_for_inventory_v3(
        product_id=product_id,
        product_title=product_title,
        signal_rows=signal_rows,
        summary_client=summary_client,
        episode_summary_rows=list(episode_summary_rows or []),
        verbose=verbose,
    )
    return build_character_inventory_v3_summaries_from_signal_rows(
        cur,
        product_id=product_id,
        signal_rows=signal_rows,
        protagonist_resolution=protagonist_resolution,
    )


def build_character_signal_provenance_map(signal_rows: list[dict]) -> dict[str, list[str]]:
    signal_provenance_map: dict[str, list[str]] = {}
    for row in signal_rows:
        payload = extract_json_object(str(row.get("summary_text") or "")) or {}
        summary_component = f"{int(row.get('summary_id') or 0)}:{str(row.get('source_hash') or '')}"
        for item in list(payload.get("mentioned_characters") or []):
            if not isinstance(item, dict):
                continue
            character_key = str(item.get("character_key") or "").strip()
            if not character_key:
                continue
            signal_provenance_map.setdefault(character_key, [])
            if summary_component not in signal_provenance_map[character_key]:
                signal_provenance_map[character_key].append(summary_component)
    return signal_provenance_map


def build_character_inventory_source_hash(
    *,
    item: dict[str, object],
    signal_provenance_map: dict[str, list[str]],
) -> str:
    scope_key = str(item.get("character_key") or "").strip()
    return build_compound_summary_source_hash(
        CHARACTER_INVENTORY_FORMAT_VERSION,
        [
            scope_key,
            *signal_provenance_map.get(scope_key, []),
            f"first:{int(item.get('first_seen_episode_no') or 0)}",
            f"latest:{int(item.get('latest_seen_episode_no') or 0)}",
            f"mentions:{int(item.get('summary_mention_count') or 0)}",
            f"voice:{int(item.get('voice_evidence_count') or 0)}",
            f"aliases:{','.join(str(value) for value in list(item.get('aliases') or []))}",
            f"actions:{','.join(str(value) for value in list(item.get('dominant_action_tags') or []))}",
            f"affects:{','.join(str(value) for value in list(item.get('dominant_affect_tags') or []))}",
        ],
    )


def upsert_character_inventory_item(
    cur,
    *,
    product_id: int,
    item: dict[str, object],
    signal_provenance_map: dict[str, list[str]],
) -> bool:
    scope_key = str(item.get("character_key") or "").strip()
    if not scope_key:
        return False
    _, inserted = upsert_summary(
        cur=cur,
        product_id=product_id,
        summary_type="character_inventory",
        scope_key=scope_key,
        source_hash=build_character_inventory_source_hash(item=item, signal_provenance_map=signal_provenance_map),
        source_doc_count=max(int(item.get("distinct_episode_count") or 0), 1),
        episode_from=int(item.get("first_seen_episode_no") or 0) or None,
        episode_to=int(item.get("latest_seen_episode_no") or 0) or None,
        summary_text=json.dumps(item, ensure_ascii=False),
    )
    return inserted


def build_low_medium_high_max(left: str, right: str) -> str:
    order = {"low": 0, "medium": 1, "high": 2}
    normalized_left = str(left or "").strip().lower() or "low"
    normalized_right = str(right or "").strip().lower() or "low"
    return normalized_left if order.get(normalized_left, 0) >= order.get(normalized_right, 0) else normalized_right


def merge_character_inventory_item(
    *,
    old_item: dict[str, object] | None,
    new_item: dict[str, object],
) -> dict[str, object]:
    if not old_item:
        return dict(new_item)

    merged = dict(new_item)
    old_display_name = str(old_item.get("display_name") or "").strip()
    new_display_name = str(new_item.get("display_name") or "").strip()
    alias_candidates = {
        str(value).strip()
        for value in list(old_item.get("aliases") or []) + list(new_item.get("aliases") or [])
        if str(value).strip()
    }
    if old_display_name:
        alias_candidates.add(old_display_name)
    if new_display_name:
        alias_candidates.add(new_display_name)

    old_evidence_episode_nos = [int(value) for value in list(old_item.get("evidence_episode_nos") or []) if int(value) > 0]
    new_evidence_episode_nos = [int(value) for value in list(new_item.get("evidence_episode_nos") or []) if int(value) > 0]
    merged_episode_nos = sorted(set(old_evidence_episode_nos + new_evidence_episode_nos))

    merged["display_name"] = old_display_name or new_display_name
    merged["entity_kind"] = str(old_item.get("entity_kind") or "").strip() or str(new_item.get("entity_kind") or "").strip()
    merged["is_protagonist"] = parse_yes_no_flag(old_item.get("is_protagonist")) or parse_yes_no_flag(new_item.get("is_protagonist"))
    merged["is_first_person"] = parse_yes_no_flag(old_item.get("is_first_person")) or parse_yes_no_flag(new_item.get("is_first_person"))
    merged["aliases"] = sorted(alias_candidates)[:8]
    merged["first_seen_episode_no"] = min(
        value
        for value in [
            int(old_item.get("first_seen_episode_no") or 0),
            int(new_item.get("first_seen_episode_no") or 0),
        ]
        if value > 0
    ) if any(
        int(value or 0) > 0
        for value in [old_item.get("first_seen_episode_no"), new_item.get("first_seen_episode_no")]
    ) else 0
    merged["latest_seen_episode_no"] = max(
        int(old_item.get("latest_seen_episode_no") or 0),
        int(new_item.get("latest_seen_episode_no") or 0),
    )
    merged["evidence_episode_nos"] = merged_episode_nos[:120]
    merged["distinct_episode_count"] = max(len(merged_episode_nos), int(new_item.get("distinct_episode_count") or 0), int(old_item.get("distinct_episode_count") or 0))
    merged["summary_mention_count"] = max(int(old_item.get("summary_mention_count") or 0), int(new_item.get("summary_mention_count") or 0))
    merged["voice_evidence_count"] = max(int(old_item.get("voice_evidence_count") or 0), int(new_item.get("voice_evidence_count") or 0))
    merged["relation_episode_count"] = max(int(old_item.get("relation_episode_count") or 0), int(new_item.get("relation_episode_count") or 0))
    old_scene_weight_counts = dict(old_item.get("scene_weight_counts") or {})
    new_scene_weight_counts = dict(new_item.get("scene_weight_counts") or {})
    merged["scene_weight_counts"] = {
        "high": max(int(old_scene_weight_counts.get("high") or 0), int(new_scene_weight_counts.get("high") or 0)),
        "medium": max(int(old_scene_weight_counts.get("medium") or 0), int(new_scene_weight_counts.get("medium") or 0)),
        "low": max(int(old_scene_weight_counts.get("low") or 0), int(new_scene_weight_counts.get("low") or 0)),
    }
    merged["scene_centrality"] = build_low_medium_high_max(
        str(old_item.get("scene_centrality") or ""),
        str(new_item.get("scene_centrality") or ""),
    )
    merged["alias_stability"] = build_low_medium_high_max(
        str(old_item.get("alias_stability") or ""),
        str(new_item.get("alias_stability") or ""),
    )
    merged["action_presence"] = build_low_medium_high_max(
        str(old_item.get("action_presence") or ""),
        str(new_item.get("action_presence") or ""),
    )
    merged["relation_presence"] = build_low_medium_high_max(
        str(old_item.get("relation_presence") or ""),
        str(new_item.get("relation_presence") or ""),
    )
    merged["dominant_action_tags"] = list(new_item.get("dominant_action_tags") or old_item.get("dominant_action_tags") or [])[:5]
    merged["dominant_affect_tags"] = list(new_item.get("dominant_affect_tags") or old_item.get("dominant_affect_tags") or [])[:5]
    return merged


def should_skip_new_character_inventory_candidate(
    *,
    candidate_item: dict[str, object],
    old_inventory_map: dict[str, dict[str, object]],
) -> tuple[bool, str]:
    candidate_key = str(candidate_item.get("character_key") or "").strip()
    candidate_name = str(candidate_item.get("display_name") or "").strip()
    candidate_aliases = {
        str(value).strip()
        for value in list(candidate_item.get("aliases") or [])
        if str(value).strip()
    }
    candidate_names = ({candidate_name} | candidate_aliases) - {""}
    if not candidate_names:
        return False, ""

    candidate_is_protagonist_key = candidate_key.startswith("protagonist:")

    for old_key, old_item in old_inventory_map.items():
        if old_key == candidate_key:
            continue
        old_name = str(old_item.get("display_name") or "").strip()
        old_aliases = {
            str(value).strip()
            for value in list(old_item.get("aliases") or [])
            if str(value).strip()
        }
        old_names = ({old_name} | old_aliases) - {""}
        old_is_protagonist_key = old_key.startswith("protagonist:")
        if (
            candidate_name
            and old_name
            and candidate_name == old_name
            and (candidate_is_protagonist_key or old_is_protagonist_key)
        ):
            return True, "duplicate_protagonist_named_identity"

    weak_evidence = (
        int(candidate_item.get("distinct_episode_count") or 0) <= 1
        and int(candidate_item.get("summary_mention_count") or 0) <= 1
    )
    if not weak_evidence:
        return False, ""

    for old_key, old_item in old_inventory_map.items():
        if old_key == candidate_key:
            continue
        old_name = str(old_item.get("display_name") or "").strip()
        old_aliases = {
            str(value).strip()
            for value in list(old_item.get("aliases") or [])
            if str(value).strip()
        }
        old_names = ({old_name} | old_aliases) - {""}
        if candidate_names & old_names:
            return True, "duplicate_identity_weak_evidence"

    return False, ""


def extract_character_keys_from_signal_rows(signal_rows: list[dict]) -> set[str]:
    character_keys: set[str] = set()
    for row in signal_rows:
        payload = extract_json_object(str(row.get("summary_text") or "")) or {}
        for item in list(payload.get("mentioned_characters") or []):
            if not isinstance(item, dict):
                continue
            character_key = str(item.get("character_key") or "").strip()
            if character_key:
                character_keys.add(character_key)
    return character_keys


def build_character_inventory_summaries(
    cur,
    *,
    product_id: int,
) -> tuple[int, int]:
    signal_rows = fetch_active_summary_rows(cur=cur, product_id=product_id, summary_type="episode_character_signals")
    inventory_rows = aggregate_character_inventory_rows(signal_rows)
    if signal_rows and not inventory_rows:
        raise ValueError(f"character_inventory aggregation returned 0 rows despite active signals: product_id={product_id}")
    inserted_count = 0
    reused_count = 0
    valid_scope_keys: set[str] = set()
    signal_provenance_map = build_character_signal_provenance_map(signal_rows)
    for item in inventory_rows:
        scope_key = str(item.get("character_key") or "").strip()
        if not scope_key:
            continue
        valid_scope_keys.add(scope_key)
        inserted = upsert_character_inventory_item(
            cur,
            product_id=product_id,
            item=item,
            signal_provenance_map=signal_provenance_map,
        )
        if inserted:
            inserted_count += 1
        else:
            reused_count += 1

    deactivate_missing_active_scopes(cur, product_id, "character_inventory", valid_scope_keys)
    return inserted_count, reused_count


def aggregate_relation_inventory_rows(signal_rows: list[dict]) -> list[dict[str, object]]:
    relation_map: dict[str, dict[str, object]] = {}

    def _accumulate_edge(
        *,
        relation_key: str,
        source_key: str,
        source_display_name: str,
        target_key: str,
        target_display_name: str,
        relation_tag: str,
        episode_no: int,
        summary_component: str,
    ) -> None:
        current = relation_map.setdefault(
            relation_key,
            {
                "relation_key": relation_key,
                "source_key": source_key,
                "source_display_name": source_display_name,
                "target_key": target_key,
                "target_display_name": target_display_name,
                "episode_nos": set(),
                "summary_components": set(),
                "relation_tag_counts": {},
                "edge_count": 0,
            },
        )
        if episode_no > 0:
            current["episode_nos"].add(episode_no)
        if summary_component:
            current["summary_components"].add(summary_component)
        current["edge_count"] += 1
        if relation_tag:
            current["relation_tag_counts"][relation_tag] = int(current["relation_tag_counts"].get(relation_tag) or 0) + 1

    for row in signal_rows:
        payload = extract_json_object(str(row.get("summary_text") or "")) or {}
        episode_no = int(payload.get("episode_no") or row.get("episode_from") or 0)
        summary_component = f"{int(row.get('summary_id') or 0)}:{str(row.get('source_hash') or '')}"
        display_name_by_key: dict[str, str] = {}
        mentioned_characters = list(payload.get("mentioned_characters") or [])
        for item in mentioned_characters:
            if not isinstance(item, dict):
                continue
            character_key = str(item.get("character_key") or "").strip()
            display_name = str(item.get("display_name") or "").strip()
            if character_key and display_name:
                display_name_by_key[character_key] = display_name
        for item in mentioned_characters:
            if not isinstance(item, dict):
                continue
            source_key = str(item.get("character_key") or "").strip()
            source_display_name = str(item.get("display_name") or "").strip()
            if not source_key or not source_display_name:
                continue
            for edge in list(item.get("relation_edges") or []):
                if not isinstance(edge, dict):
                    continue
                target_key = str(edge.get("target_key") or "").strip()
                target_label = str(edge.get("target_label") or "").strip()
                relation_tag = str(edge.get("relation_tag") or "").strip()
                direction = str(edge.get("direction") or "").strip().lower()
                if not target_key or not relation_tag or target_key == source_key:
                    continue
                target_display_name = display_name_by_key.get(target_key) or target_label or target_key
                if direction == "from_target":
                    _accumulate_edge(
                        relation_key=f"{target_key}=>{source_key}",
                        source_key=target_key,
                        source_display_name=target_display_name,
                        target_key=source_key,
                        target_display_name=source_display_name,
                        relation_tag=relation_tag,
                        episode_no=episode_no,
                        summary_component=summary_component,
                    )
                elif direction == "mutual":
                    _accumulate_edge(
                        relation_key=f"{source_key}=>{target_key}",
                        source_key=source_key,
                        source_display_name=source_display_name,
                        target_key=target_key,
                        target_display_name=target_display_name,
                        relation_tag=relation_tag,
                        episode_no=episode_no,
                        summary_component=summary_component,
                    )
                    _accumulate_edge(
                        relation_key=f"{target_key}=>{source_key}",
                        source_key=target_key,
                        source_display_name=target_display_name,
                        target_key=source_key,
                        target_display_name=source_display_name,
                        relation_tag=relation_tag,
                        episode_no=episode_no,
                        summary_component=summary_component,
                    )
                else:
                    _accumulate_edge(
                        relation_key=f"{source_key}=>{target_key}",
                        source_key=source_key,
                        source_display_name=source_display_name,
                        target_key=target_key,
                        target_display_name=target_display_name,
                        relation_tag=relation_tag,
                        episode_no=episode_no,
                        summary_component=summary_component,
                    )

    relation_rows: list[dict[str, object]] = []
    for current in relation_map.values():
        episode_nos = sorted(int(value) for value in set(current["episode_nos"]))
        distinct_episode_count = len(episode_nos)
        relation_rows.append(
            {
                "relation_key": str(current["relation_key"]),
                "source_key": str(current["source_key"]),
                "source_display_name": str(current["source_display_name"]),
                "target_key": str(current["target_key"]),
                "target_display_name": str(current["target_display_name"]),
                "first_seen_episode_no": episode_nos[0] if episode_nos else 0,
                "latest_seen_episode_no": episode_nos[-1] if episode_nos else 0,
                "distinct_episode_count": distinct_episode_count,
                "edge_count": int(current["edge_count"] or 0),
                "relation_intensity": (
                    "high"
                    if distinct_episode_count >= 4
                    else "medium"
                    if distinct_episode_count >= 2
                    else "low"
                ),
                "dominant_relation_tags": [
                    key
                    for key, _ in sorted(current["relation_tag_counts"].items(), key=lambda item: (-item[1], item[0]))[:6]
                ],
                "summary_components": sorted(set(str(value) for value in current["summary_components"] if str(value).strip())),
            }
        )

    return sorted(
        relation_rows,
        key=lambda item: (
            -int(item["distinct_episode_count"] or 0),
            -int(item["edge_count"] or 0),
            str(item["source_display_name"]),
            str(item["target_display_name"]),
        ),
    )


def build_relation_inventory_source_hash(*, item: dict[str, object]) -> str:
    return build_compound_summary_source_hash(
        RELATION_INVENTORY_FORMAT_VERSION,
        [
            str(item.get("relation_key") or "").strip(),
            *list(item.get("summary_components") or []),
            f"first:{int(item.get('first_seen_episode_no') or 0)}",
            f"latest:{int(item.get('latest_seen_episode_no') or 0)}",
            f"count:{int(item.get('distinct_episode_count') or 0)}",
            f"tags:{','.join(str(value) for value in list(item.get('dominant_relation_tags') or []))}",
        ],
    )


def upsert_relation_inventory_item(
    cur,
    *,
    product_id: int,
    item: dict[str, object],
) -> bool:
    scope_key = str(item.get("relation_key") or "").strip()
    if not scope_key:
        return False
    payload = dict(item)
    payload.pop("summary_components", None)
    _, inserted = upsert_summary(
        cur=cur,
        product_id=product_id,
        summary_type="relation_inventory",
        scope_key=scope_key,
        source_hash=build_relation_inventory_source_hash(item=item),
        source_doc_count=max(int(item.get("distinct_episode_count") or 0), 1),
        episode_from=int(item.get("first_seen_episode_no") or 0) or None,
        episode_to=int(item.get("latest_seen_episode_no") or 0) or None,
        summary_text=json.dumps(payload, ensure_ascii=False),
    )
    return inserted


def merge_relation_inventory_item(
    *,
    old_item: dict[str, object] | None,
    new_item: dict[str, object],
) -> dict[str, object]:
    if not old_item:
        return dict(new_item)

    merged = dict(new_item)
    old_summary_components = [str(value).strip() for value in list(old_item.get("summary_components") or []) if str(value).strip()]
    new_summary_components = [str(value).strip() for value in list(new_item.get("summary_components") or []) if str(value).strip()]
    merged["relation_key"] = str(old_item.get("relation_key") or "").strip() or str(new_item.get("relation_key") or "").strip()
    merged["source_key"] = str(old_item.get("source_key") or "").strip() or str(new_item.get("source_key") or "").strip()
    merged["target_key"] = str(old_item.get("target_key") or "").strip() or str(new_item.get("target_key") or "").strip()
    merged["source_display_name"] = str(old_item.get("source_display_name") or "").strip() or str(new_item.get("source_display_name") or "").strip()
    merged["target_display_name"] = str(old_item.get("target_display_name") or "").strip() or str(new_item.get("target_display_name") or "").strip()
    merged["first_seen_episode_no"] = min(
        value
        for value in [
            int(old_item.get("first_seen_episode_no") or 0),
            int(new_item.get("first_seen_episode_no") or 0),
        ]
        if value > 0
    ) if any(
        int(value or 0) > 0
        for value in [old_item.get("first_seen_episode_no"), new_item.get("first_seen_episode_no")]
    ) else 0
    merged["latest_seen_episode_no"] = max(
        int(old_item.get("latest_seen_episode_no") or 0),
        int(new_item.get("latest_seen_episode_no") or 0),
    )
    merged["distinct_episode_count"] = max(int(old_item.get("distinct_episode_count") or 0), int(new_item.get("distinct_episode_count") or 0))
    merged["edge_count"] = max(int(old_item.get("edge_count") or 0), int(new_item.get("edge_count") or 0))
    merged["relation_intensity"] = build_low_medium_high_max(
        str(old_item.get("relation_intensity") or ""),
        str(new_item.get("relation_intensity") or ""),
    )
    merged["dominant_relation_tags"] = list(dict.fromkeys(
        [str(value).strip() for value in list(new_item.get("dominant_relation_tags") or []) if str(value).strip()]
        + [str(value).strip() for value in list(old_item.get("dominant_relation_tags") or []) if str(value).strip()]
    ))[:6]
    merged["summary_components"] = list(dict.fromkeys(new_summary_components + old_summary_components))
    return merged


def should_skip_new_relation_inventory_candidate(
    *,
    candidate_item: dict[str, object],
    old_relation_map: dict[str, dict[str, object]],
) -> tuple[bool, str]:
    source_name = str(candidate_item.get("source_display_name") or "").strip()
    target_name = str(candidate_item.get("target_display_name") or "").strip()
    if not source_name or not target_name:
        return False, ""

    for old_item in old_relation_map.values():
        old_source = str(old_item.get("source_display_name") or "").strip()
        old_target = str(old_item.get("target_display_name") or "").strip()
        if source_name == old_source and target_name == old_target:
            return True, "duplicate_relation_display_pair"

    weak_evidence = (
        int(candidate_item.get("distinct_episode_count") or 0) <= 1
        and int(candidate_item.get("edge_count") or 0) <= 1
    )
    if not weak_evidence:
        return False, ""

    return False, ""


def extract_relation_keys_from_signal_rows(signal_rows: list[dict]) -> set[str]:
    relation_keys: set[str] = set()
    for row in signal_rows:
        payload = extract_json_object(str(row.get("summary_text") or "")) or {}
        episode_no = int(payload.get("episode_no") or row.get("episode_from") or 0)
        summary_component = f"{int(row.get('summary_id') or 0)}:{str(row.get('source_hash') or '')}"
        mentioned_characters = list(payload.get("mentioned_characters") or [])
        display_name_by_key: dict[str, str] = {}
        for item in mentioned_characters:
            if not isinstance(item, dict):
                continue
            character_key = str(item.get("character_key") or "").strip()
            display_name = str(item.get("display_name") or "").strip()
            if character_key and display_name:
                display_name_by_key[character_key] = display_name
        for item in mentioned_characters:
            if not isinstance(item, dict):
                continue
            source_key = str(item.get("character_key") or "").strip()
            source_display_name = str(item.get("display_name") or "").strip()
            if not source_key or not source_display_name:
                continue
            for edge in list(item.get("relation_edges") or []):
                if not isinstance(edge, dict):
                    continue
                target_key = str(edge.get("target_key") or "").strip()
                relation_tag = str(edge.get("relation_tag") or "").strip()
                direction = str(edge.get("direction") or "").strip().lower()
                if not target_key or not relation_tag or target_key == source_key:
                    continue
                if direction == "from_target":
                    relation_keys.add(f"{target_key}=>{source_key}")
                elif direction == "mutual":
                    relation_keys.add(f"{source_key}=>{target_key}")
                    relation_keys.add(f"{target_key}=>{source_key}")
                else:
                    relation_keys.add(f"{source_key}=>{target_key}")
    return relation_keys


def build_relation_inventory_summaries(
    cur,
    *,
    product_id: int,
) -> tuple[int, int]:
    signal_rows = fetch_active_summary_rows(cur=cur, product_id=product_id, summary_type="episode_character_signals")
    relation_rows = aggregate_relation_inventory_rows(signal_rows)
    inserted_count = 0
    reused_count = 0
    valid_scope_keys: set[str] = set()
    for item in relation_rows:
        scope_key = str(item.get("relation_key") or "").strip()
        if not scope_key:
            continue
        valid_scope_keys.add(scope_key)
        inserted = upsert_relation_inventory_item(cur, product_id=product_id, item=item)
        if inserted:
            inserted_count += 1
        else:
            reused_count += 1

    deactivate_missing_active_scopes(cur, product_id, "relation_inventory", valid_scope_keys)
    return inserted_count, reused_count


def build_character_inventory_summaries_delta(
    cur,
    *,
    product_id: int,
    old_inventory_map: dict[str, dict[str, object]],
    old_touched_signal_rows: list[dict],
    new_touched_signal_rows: list[dict],
) -> tuple[int, int]:
    active_signal_rows = fetch_active_summary_rows(cur=cur, product_id=product_id, summary_type="episode_character_signals")
    candidate_rows = aggregate_character_inventory_rows(active_signal_rows)
    candidate_map = {
        str(item.get("character_key") or "").strip(): item
        for item in candidate_rows
        if str(item.get("character_key") or "").strip()
    }
    touched_character_keys = extract_character_keys_from_signal_rows(old_touched_signal_rows) | extract_character_keys_from_signal_rows(new_touched_signal_rows)
    signal_provenance_map = build_character_signal_provenance_map(active_signal_rows)

    inserted_count = 0
    reused_count = 0
    keep_old_missing_count = 0
    skip_new_count = 0
    for character_key in sorted(touched_character_keys):
        candidate = candidate_map.get(character_key)
        if not candidate:
            if character_key in old_inventory_map:
                logger.info(
                    "story_agent_delta_character_keep_old product_id=%s character_key=%s reason=%s",
                    product_id,
                    character_key,
                    "candidate_missing_keep_old",
                )
                keep_old_missing_count += 1
            continue
        if character_key not in old_inventory_map:
            skip_new, skip_reason = should_skip_new_character_inventory_candidate(
                candidate_item=candidate,
                old_inventory_map=old_inventory_map,
            )
            if skip_new:
                logger.warning(
                    "story_agent_delta_character_skip_new product_id=%s character_key=%s reason=%s",
                    product_id,
                    character_key,
                    skip_reason,
                )
                skip_new_count += 1
                reused_count += 1
                continue
        merged_item = merge_character_inventory_item(
            old_item=old_inventory_map.get(character_key),
            new_item=candidate,
        )
        inserted = upsert_character_inventory_item(
            cur,
            product_id=product_id,
            item=merged_item,
            signal_provenance_map=signal_provenance_map,
        )
        if inserted:
            inserted_count += 1
        else:
            reused_count += 1
    logger.info(
        "story_agent_delta_character_summary product_id=%s touched=%s inserted=%s reused=%s keep_old_missing=%s skip_new=%s",
        product_id,
        len(touched_character_keys),
        inserted_count,
        reused_count,
        keep_old_missing_count,
        skip_new_count,
    )
    return {
        "inserted_count": inserted_count,
        "reused_count": reused_count,
        "keep_old_missing_count": keep_old_missing_count,
        "skip_new_count": skip_new_count,
        "touched_key_count": len(touched_character_keys),
    }


def build_relation_inventory_summaries_delta(
    cur,
    *,
    product_id: int,
    old_relation_map: dict[str, dict[str, object]],
    old_touched_signal_rows: list[dict],
    new_touched_signal_rows: list[dict],
) -> tuple[int, int]:
    active_signal_rows = fetch_active_summary_rows(cur=cur, product_id=product_id, summary_type="episode_character_signals")
    candidate_rows = aggregate_relation_inventory_rows(active_signal_rows)
    candidate_map = {
        str(item.get("relation_key") or "").strip(): item
        for item in candidate_rows
        if str(item.get("relation_key") or "").strip()
    }
    touched_relation_keys = extract_relation_keys_from_signal_rows(old_touched_signal_rows) | extract_relation_keys_from_signal_rows(new_touched_signal_rows)

    inserted_count = 0
    reused_count = 0
    keep_old_missing_count = 0
    skip_new_count = 0
    for relation_key in sorted(touched_relation_keys):
        candidate = candidate_map.get(relation_key)
        if not candidate:
            if relation_key in old_relation_map:
                logger.info(
                    "story_agent_delta_relation_keep_old product_id=%s relation_key=%s reason=%s",
                    product_id,
                    relation_key,
                    "candidate_missing_keep_old",
                )
                keep_old_missing_count += 1
            continue
        if relation_key not in old_relation_map:
            skip_new, skip_reason = should_skip_new_relation_inventory_candidate(
                candidate_item=candidate,
                old_relation_map=old_relation_map,
            )
            if skip_new:
                logger.warning(
                    "story_agent_delta_relation_skip_new product_id=%s relation_key=%s reason=%s",
                    product_id,
                    relation_key,
                    skip_reason,
                )
                skip_new_count += 1
                reused_count += 1
                continue
        merged_item = merge_relation_inventory_item(
            old_item=old_relation_map.get(relation_key),
            new_item=candidate,
        )
        inserted = upsert_relation_inventory_item(
            cur,
            product_id=product_id,
            item=merged_item,
        )
        if inserted:
            inserted_count += 1
        else:
            reused_count += 1
    logger.info(
        "story_agent_delta_relation_summary product_id=%s touched=%s inserted=%s reused=%s keep_old_missing=%s skip_new=%s",
        product_id,
        len(touched_relation_keys),
        inserted_count,
        reused_count,
        keep_old_missing_count,
        skip_new_count,
    )
    return {
        "inserted_count": inserted_count,
        "reused_count": reused_count,
        "keep_old_missing_count": keep_old_missing_count,
        "skip_new_count": skip_new_count,
        "touched_key_count": len(touched_relation_keys),
    }


def fetch_active_character_inventory_map(
    cur,
    *,
    product_id: int,
    summary_type: str = "character_inventory",
) -> dict[str, dict[str, object]]:
    inventory_rows = fetch_active_summary_rows(cur=cur, product_id=product_id, summary_type=summary_type)
    inventory_map: dict[str, dict[str, object]] = {}
    for row in inventory_rows:
        scope_key = str(row.get("scope_key") or "").strip()
        if not scope_key:
            continue
        payload = extract_json_object(str(row.get("summary_text") or "")) or {}
        if not isinstance(payload, dict):
            continue
        inventory_map[scope_key] = payload
    return inventory_map


def fetch_rp_ready_character_inventory_history_state_map(
    cur,
    *,
    product_id: int,
) -> dict[str, dict[str, object]]:
    cur.execute(
        """
        SELECT inventory.summary_id,
               inventory.scope_key,
               inventory.summary_text
          FROM tb_story_agent_context_summary inventory
         WHERE inventory.product_id = %s
           AND inventory.summary_type = 'character_inventory_v3'
           AND EXISTS (
               SELECT 1
                 FROM tb_story_agent_context_summary profile
                WHERE profile.product_id = inventory.product_id
                  AND profile.scope_key = inventory.scope_key
                  AND profile.summary_type = 'character_rp_profile'
                  AND profile.is_active = 'Y'
           )
           AND EXISTS (
               SELECT 1
                 FROM tb_story_agent_context_summary examples
                WHERE examples.product_id = inventory.product_id
                  AND examples.scope_key = inventory.scope_key
                  AND examples.summary_type = 'character_rp_examples'
                  AND examples.is_active = 'Y'
           )
         ORDER BY inventory.summary_id DESC
        """,
        (product_id,),
    )
    history_state_map: dict[str, dict[str, object]] = {}
    for row in cur.fetchall():
        scope_key = str(row.get("scope_key") or "").strip()
        if not scope_key or scope_key in history_state_map:
            continue
        payload = extract_json_object(str(row.get("summary_text") or "")) or {}
        if not isinstance(payload, dict):
            continue
        history_state_map[scope_key] = {
            "summary_id": int(row.get("summary_id") or 0),
            "scope_key": scope_key,
            "payload": payload,
        }
    return history_state_map


def fetch_active_relation_inventory_map(cur, *, product_id: int) -> dict[str, list[dict[str, object]]]:
    relation_rows = fetch_active_summary_rows(cur=cur, product_id=product_id, summary_type="relation_inventory")
    relation_map: dict[str, list[dict[str, object]]] = {}
    for row in relation_rows:
        payload = extract_json_object(str(row.get("summary_text") or "")) or {}
        if not isinstance(payload, dict):
            continue
        source_key = str(payload.get("source_key") or "").strip()
        if not source_key:
            continue
        relation_map.setdefault(source_key, []).append(payload)
    for source_key, items in relation_map.items():
        relation_map[source_key] = sorted(
            items,
            key=lambda item: (
                -int(item.get("distinct_episode_count") or 0),
                -int(item.get("edge_count") or 0),
                str(item.get("target_display_name") or ""),
            ),
        )
    return relation_map


def build_canonical_relation_inventory_map(
    *,
    relation_map: dict[str, list[dict[str, object]]],
    inventory_map: dict[str, dict[str, object]],
) -> dict[str, list[dict[str, object]]]:
    source_scope_key_map = build_inventory_source_scope_key_map(inventory_map or {})
    canonical_relation_map: dict[str, list[dict[str, object]]] = {}
    for relation_source_key, items in (relation_map or {}).items():
        for item in list(items or []):
            payload = dict(item or {})
            source_key = str(payload.get("source_key") or relation_source_key or "").strip()
            canonical_source_key = source_scope_key_map.get(source_key, source_key)
            if not canonical_source_key:
                continue
            canonical_relation_map.setdefault(canonical_source_key, []).append(payload)
    return canonical_relation_map


def fetch_active_relation_inventory_by_relation_key_map(cur, *, product_id: int) -> dict[str, dict[str, object]]:
    relation_rows = fetch_active_summary_rows(cur=cur, product_id=product_id, summary_type="relation_inventory")
    relation_map: dict[str, dict[str, object]] = {}
    for row in relation_rows:
        payload = extract_json_object(str(row.get("summary_text") or "")) or {}
        if not isinstance(payload, dict):
            continue
        relation_key = str(payload.get("relation_key") or "").strip()
        if not relation_key:
            continue
        relation_map[relation_key] = payload
    return relation_map


def fetch_active_summary_state_map(
    cur,
    *,
    product_id: int,
    summary_type: str,
) -> dict[str, dict[str, object]]:
    rows = fetch_active_summary_rows(cur=cur, product_id=product_id, summary_type=summary_type)
    state_map: dict[str, dict[str, object]] = {}
    for row in rows:
        scope_key = str(row.get("scope_key") or "").strip()
        if not scope_key:
            continue
        payload = extract_json_object(str(row.get("summary_text") or "")) or {}
        state_map[scope_key] = {
            "summary_id": int(row.get("summary_id") or 0),
            "scope_key": scope_key,
            "source_hash": str(row.get("source_hash") or "").strip(),
            "payload": payload if isinstance(payload, dict) else {},
        }
    return state_map


def fetch_active_episode_texts_by_no(cur, *, product_id: int) -> dict[int, str]:
    cur.execute(
        """
        SELECT d.episode_no, c.chunk_no, c.text
          FROM tb_story_agent_context_doc d
          JOIN tb_story_agent_context_chunk c
            ON c.context_doc_id = d.context_doc_id
         WHERE d.product_id = %s
           AND d.is_active = 'Y'
         ORDER BY d.episode_no ASC, c.chunk_no ASC
        """,
        (product_id,),
    )
    chunks_by_episode_no: dict[int, list[str]] = {}
    for row in cur.fetchall():
        episode_no = int(row.get("episode_no") or 0)
        text_value = str(row.get("text") or "").strip()
        if episode_no <= 0 or not text_value:
            continue
        chunks_by_episode_no.setdefault(episode_no, []).append(text_value)
    return {
        episode_no: "\n\n".join(chunks)
        for episode_no, chunks in chunks_by_episode_no.items()
        if chunks
    }


def fetch_active_summary_payload_rows(
    cur,
    *,
    product_id: int,
    summary_type: str,
) -> list[dict[str, object]]:
    rows = fetch_active_summary_rows(cur=cur, product_id=product_id, summary_type=summary_type)
    parsed_rows: list[dict[str, object]] = []
    for row in rows:
        payload = extract_json_object(str(row.get("summary_text") or "")) or {}
        if not isinstance(payload, dict):
            continue
        parsed_rows.append(
            {
                "summary_id": int(row.get("summary_id") or 0),
                "scope_key": str(row.get("scope_key") or "").strip(),
                "payload": payload,
            }
        )
    return parsed_rows


def deactivate_summary_ids(cur, summary_ids: Iterable[int]) -> int:
    unique_ids = sorted(set(int(value) for value in summary_ids if int(value) > 0))
    if not unique_ids:
        return 0
    placeholders = ", ".join(["%s"] * len(unique_ids))
    cur.execute(
        f"""
        UPDATE tb_story_agent_context_summary
           SET is_active = 'N'
         WHERE summary_id IN ({placeholders})
           AND is_active = 'Y'
        """,
        tuple(unique_ids),
    )
    return int(cur.rowcount or 0)


def build_character_cleanup_sort_key(row: dict[str, object]) -> tuple[int, int, int, int, int, int]:
    payload = dict(row.get("payload") or {})
    return (
        int(payload.get("distinct_episode_count") or 0),
        int(payload.get("summary_mention_count") or 0),
        1 if bool(payload.get("is_protagonist")) else 0,
        1 if bool(payload.get("is_first_person")) else 0,
        int(payload.get("latest_seen_episode_no") or 0),
        int(row.get("summary_id") or 0),
    )


def cleanup_duplicate_character_inventory_rows(
    cur,
    *,
    product_id: int,
) -> dict[str, object]:
    parsed_rows = fetch_active_summary_payload_rows(cur, product_id=product_id, summary_type="character_inventory")
    rows_by_display_name: dict[str, list[dict[str, object]]] = {}
    for row in parsed_rows:
        payload = dict(row.get("payload") or {})
        display_name = str(payload.get("display_name") or "").strip()
        if not display_name:
            continue
        rows_by_display_name.setdefault(display_name, []).append(row)

    duplicate_groups = 0
    deactivated_ids: list[int] = []
    kept_summary_ids: set[int] = set()
    touched_scope_keys: set[str] = set()
    for display_name, items in rows_by_display_name.items():
        if len(items) <= 1:
            kept_summary_ids.add(int(items[0].get("summary_id") or 0))
            continue
        duplicate_groups += 1
        keep_row = max(items, key=build_character_cleanup_sort_key)
        keep_scope_key = str(keep_row.get("scope_key") or "").strip()
        if keep_scope_key:
            touched_scope_keys.add(keep_scope_key)
        keep_summary_id = int(keep_row.get("summary_id") or 0)
        kept_summary_ids.add(keep_summary_id)
        for item in items:
            summary_id = int(item.get("summary_id") or 0)
            if summary_id and summary_id != keep_summary_id:
                deactivated_ids.append(summary_id)
                dropped_scope_key = str(item.get("scope_key") or "").strip()
                if dropped_scope_key:
                    touched_scope_keys.add(dropped_scope_key)
        logger.warning(
            "story_agent_delta_character_cleanup product_id=%s display_name=%s kept_scope_key=%s dropped=%s",
            product_id,
            display_name,
            str(keep_row.get("scope_key") or ""),
            len(items) - 1,
        )

    deactivated_count = deactivate_summary_ids(cur, deactivated_ids)

    active_rows_after = fetch_active_summary_payload_rows(cur, product_id=product_id, summary_type="character_inventory")
    canonical_character_key_by_display_name: dict[str, str] = {}
    for row in active_rows_after:
        payload = dict(row.get("payload") or {})
        display_name = str(payload.get("display_name") or "").strip()
        character_key = str(payload.get("character_key") or "").strip()
        if display_name and character_key:
            canonical_character_key_by_display_name.setdefault(display_name, character_key)

    return {
        "duplicate_groups": duplicate_groups,
        "deactivated_count": deactivated_count,
        "canonical_character_key_by_display_name": canonical_character_key_by_display_name,
        "touched_scope_keys": sorted(touched_scope_keys),
    }


def build_relation_cleanup_sort_key(
    row: dict[str, object],
    *,
    canonical_character_key_by_display_name: dict[str, str],
) -> tuple[int, int, int, int, int]:
    payload = dict(row.get("payload") or {})
    source_display_name = str(payload.get("source_display_name") or "").strip()
    target_display_name = str(payload.get("target_display_name") or "").strip()
    source_key = str(payload.get("source_key") or "").strip()
    target_key = str(payload.get("target_key") or "").strip()
    source_match = 1 if canonical_character_key_by_display_name.get(source_display_name) == source_key else 0
    target_match = 1 if canonical_character_key_by_display_name.get(target_display_name) == target_key else 0
    return (
        source_match + target_match,
        int(payload.get("distinct_episode_count") or 0),
        int(payload.get("edge_count") or 0),
        int(payload.get("latest_seen_episode_no") or 0),
        int(row.get("summary_id") or 0),
    )


def cleanup_duplicate_relation_inventory_rows(
    cur,
    *,
    product_id: int,
    canonical_character_key_by_display_name: dict[str, str],
) -> dict[str, object]:
    parsed_rows = fetch_active_summary_payload_rows(cur, product_id=product_id, summary_type="relation_inventory")
    rows_by_edge: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in parsed_rows:
        payload = dict(row.get("payload") or {})
        source_display_name = str(payload.get("source_display_name") or "").strip()
        target_display_name = str(payload.get("target_display_name") or "").strip()
        if not source_display_name or not target_display_name:
            continue
        rows_by_edge.setdefault((source_display_name, target_display_name), []).append(row)

    duplicate_groups = 0
    deactivated_ids: list[int] = []
    for edge_key, items in rows_by_edge.items():
        if len(items) <= 1:
            continue
        duplicate_groups += 1
        keep_row = max(
            items,
            key=lambda item: build_relation_cleanup_sort_key(
                item,
                canonical_character_key_by_display_name=canonical_character_key_by_display_name,
            ),
        )
        keep_summary_id = int(keep_row.get("summary_id") or 0)
        for item in items:
            summary_id = int(item.get("summary_id") or 0)
            if summary_id and summary_id != keep_summary_id:
                deactivated_ids.append(summary_id)
        logger.warning(
            "story_agent_delta_relation_cleanup product_id=%s edge=%s->%s kept_scope_key=%s dropped=%s",
            product_id,
            edge_key[0],
            edge_key[1],
            str(keep_row.get("scope_key") or ""),
            len(items) - 1,
        )

    deactivated_count = deactivate_summary_ids(cur, deactivated_ids)
    return {
        "duplicate_groups": duplicate_groups,
        "deactivated_count": deactivated_count,
    }


def collect_duplicate_character_display_names(
    inventory_map: dict[str, dict[str, object]],
) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for character_key, item in inventory_map.items():
        display_name = str(item.get("display_name") or "").strip()
        if not display_name:
            continue
        grouped.setdefault(display_name, []).append(character_key)
    return {
        name: sorted(keys)
        for name, keys in grouped.items()
        if len(keys) > 1
    }


def collect_duplicate_relation_edges(
    relation_map: dict[str, dict[str, object]],
) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for relation_key, item in relation_map.items():
        source_display_name = str(item.get("source_display_name") or "").strip()
        target_display_name = str(item.get("target_display_name") or "").strip()
        if not source_display_name or not target_display_name:
            continue
        edge_key = f"{source_display_name}->{target_display_name}"
        grouped.setdefault(edge_key, []).append(relation_key)
    return {
        edge_key: sorted(keys)
        for edge_key, keys in grouped.items()
        if len(keys) > 1
    }


def collect_protagonist_display_names(
    inventory_map: dict[str, dict[str, object]],
) -> set[str]:
    return {
        str(item.get("display_name") or "").strip()
        for item in inventory_map.values()
        if bool(item.get("is_protagonist")) and str(item.get("display_name") or "").strip()
    }


def build_delta_inventory_verification(
    *,
    product_id: int,
    old_inventory_map: dict[str, dict[str, object]],
    new_inventory_map: dict[str, dict[str, object]],
    old_relation_map: dict[str, dict[str, object]],
    new_relation_map: dict[str, dict[str, object]],
    old_touched_signal_rows: list[dict],
    new_touched_signal_rows: list[dict],
    character_delta_stats: dict[str, int],
    relation_delta_stats: dict[str, int],
) -> dict[str, object]:
    touched_character_keys = extract_character_keys_from_signal_rows(old_touched_signal_rows) | extract_character_keys_from_signal_rows(new_touched_signal_rows)
    touched_relation_keys = extract_relation_keys_from_signal_rows(old_touched_signal_rows) | extract_relation_keys_from_signal_rows(new_touched_signal_rows)

    old_protagonists = collect_protagonist_display_names(old_inventory_map)
    new_protagonists = collect_protagonist_display_names(new_inventory_map)
    duplicate_character_names = collect_duplicate_character_display_names(new_inventory_map)
    duplicate_relation_edges = collect_duplicate_relation_edges(new_relation_map)

    new_character_keys = sorted(
        key for key in touched_character_keys
        if key not in old_inventory_map and key in new_inventory_map
    )
    new_relation_keys = sorted(
        key for key in touched_relation_keys
        if key not in old_relation_map and key in new_relation_map
    )

    return {
        "product_id": product_id,
        "touched_character_keys": len(touched_character_keys),
        "touched_relation_keys": len(touched_relation_keys),
        "new_character_keys": len(new_character_keys),
        "new_relation_keys": len(new_relation_keys),
        "character_keep_old_missing": int(character_delta_stats.get("keep_old_missing_count") or 0),
        "character_skip_new": int(character_delta_stats.get("skip_new_count") or 0),
        "relation_keep_old_missing": int(relation_delta_stats.get("keep_old_missing_count") or 0),
        "relation_skip_new": int(relation_delta_stats.get("skip_new_count") or 0),
        "duplicate_character_names": dict(list(sorted(duplicate_character_names.items()))[:5]),
        "duplicate_relation_edges": dict(list(sorted(duplicate_relation_edges.items()))[:5]),
        "protagonist_keys_before": sorted(old_protagonists),
        "protagonist_keys_after": sorted(new_protagonists),
        "protagonist_changed": old_protagonists != new_protagonists,
    }


def build_rp_relation_context_lines(
    *,
    character_key: str,
    relation_map: dict[str, list[dict[str, object]]],
    limit: int = 4,
) -> list[str]:
    lines: list[str] = []
    for item in list(relation_map.get(character_key) or [])[:limit]:
        target_display_name = str(item.get("target_display_name") or "").strip()
        if not target_display_name:
            continue
        relation_tags = [str(value).strip() for value in (item.get("dominant_relation_tags") or []) if str(value).strip()]
        distinct_episode_count = int(item.get("distinct_episode_count") or 0)
        latest_seen_episode_no = int(item.get("latest_seen_episode_no") or 0)
        line = f"- 대상: {target_display_name}"
        if relation_tags:
            line += f" | 관계 태그: {', '.join(relation_tags[:3])}"
        if distinct_episode_count > 0:
            line += f" | 반복 화수: {distinct_episode_count}"
        if latest_seen_episode_no > 0:
            line += f" | 최근: {latest_seen_episode_no}화"
        lines.append(line)
    return lines


def build_character_chat_scene_context_lines_by_scope(
    scene_rows: list[dict[str, object]],
    *,
    limit_per_scope: int = 8,
) -> dict[str, list[str]]:
    lines_by_scope: dict[str, list[str]] = {}
    for row in scene_rows:
        payload = extract_json_object(str(row.get("summary_text") or "")) or {}
        if not isinstance(payload, dict):
            continue
        episode_no = int(payload.get("episode_no") or row.get("episode_from") or 0)
        for scene in list(payload.get("scenes") or []):
            if not isinstance(scene, dict):
                continue
            scope_keys = {
                str(item.get("scope_key") or "").strip()
                for item in list(scene.get("participants") or [])
                if isinstance(item, dict) and str(item.get("scope_key") or "").strip()
            }
            participant_names_by_scope: dict[str, set[str]] = {}
            for item in list(scene.get("participants") or []):
                if not isinstance(item, dict):
                    continue
                participant_scope_key = str(item.get("scope_key") or "").strip()
                if not participant_scope_key:
                    continue
                names = participant_names_by_scope.setdefault(participant_scope_key, set())
                for key in ("mention_label", "display_name"):
                    name_value = normalize_rp_text(str(item.get(key) or ""), limit=40)
                    if name_value:
                        names.add(name_value)
            scope_keys.update(
                str(item.get("actor_scope_key") or "").strip()
                for item in list(scene.get("action_ownership") or [])
                if isinstance(item, dict) and str(item.get("actor_scope_key") or "").strip()
            )
            if not scope_keys:
                continue

            parts = []
            scene_gist = normalize_rp_text(str(scene.get("scene_gist") or ""), limit=90)
            current_action = normalize_rp_text(str(scene.get("current_action") or ""), limit=80)
            immediate_pressure = normalize_rp_text(str(scene.get("immediate_pressure") or ""), limit=80)
            character_initiative_reason = normalize_rp_text(
                str(scene.get("character_initiative_reason") or ""),
                limit=80,
            )
            user_entry_role = normalize_rp_text(str(scene.get("user_entry_role") or ""), limit=50)
            user_hook = normalize_rp_text(str(scene.get("user_hook") or ""), limit=80)
            user_can_do = _normalize_episode_scene_text_list(scene.get("user_can_do"), limit=60, max_items=2)
            opening_grounding = _normalize_episode_scene_opening_grounding(scene.get("opening_grounding"))
            scene_identity_boundary = _normalize_episode_scene_identity_boundary(
                scene.get("scene_identity_boundary")
            )
            pressure_clock = normalize_rp_text(str(scene.get("pressure_clock") or ""), limit=80)
            conversation_fuel_tags = _normalize_episode_scene_text_list(
                scene.get("conversation_fuel_tags"),
                limit=30,
                max_items=3,
            )
            beat_ladder = _normalize_episode_scene_text_list(scene.get("beat_ladder"), limit=70, max_items=2)
            turn_continuation_contract = _normalize_episode_scene_turn_contract(
                scene.get("turn_continuation_contract")
            )
            knowledge_boundary = _normalize_episode_scene_knowledge_boundary(scene.get("knowledge_boundary"))
            progression_seed = normalize_rp_text(str(scene.get("progression_seed") or ""), limit=80)
            if scene_gist:
                parts.append(f"장면={scene_gist}")
            if current_action:
                parts.append(f"행동={current_action}")
            if immediate_pressure:
                parts.append(f"압력={immediate_pressure}")
            if character_initiative_reason:
                parts.append(f"선제이유={character_initiative_reason}")
            if user_entry_role:
                parts.append(f"유저역할={user_entry_role}")
            if user_hook:
                parts.append(f"hook={user_hook}")
            if user_can_do:
                parts.append(f"선택={'; '.join(user_can_do)}")
            place_anchor = str(opening_grounding.get("place_anchor") or "")
            sensory_anchors = list(opening_grounding.get("sensory_anchors") or [])
            prop_anchors = list(opening_grounding.get("prop_anchors") or [])
            spatial_constraints = list(opening_grounding.get("spatial_constraints") or [])
            character_visible_motion = str(opening_grounding.get("character_visible_motion") or "")
            forbidden_opening_inventions = list(opening_grounding.get("forbidden_opening_inventions") or [])
            if place_anchor:
                parts.append(f"장소={place_anchor}")
            if sensory_anchors:
                parts.append(f"감각={'; '.join(sensory_anchors[:2])}")
            if prop_anchors:
                parts.append(f"소품={'; '.join(prop_anchors[:2])}")
            if spatial_constraints:
                parts.append(f"공간={'; '.join(spatial_constraints[:2])}")
            if character_visible_motion:
                parts.append(f"가시행동={character_visible_motion}")
            if forbidden_opening_inventions:
                parts.append(f"금지장식={'; '.join(forbidden_opening_inventions[:2])}")
            allowed_address_names = list(scene_identity_boundary.get("allowed_address_names") or [])
            must_not_address_as = list(scene_identity_boundary.get("must_not_address_as") or [])
            surface_role_for_user = str(scene_identity_boundary.get("surface_role_for_user") or "")
            identity_spoiler_risk = str(scene_identity_boundary.get("identity_spoiler_risk") or "")
            if pressure_clock:
                parts.append(f"시계={pressure_clock}")
            if conversation_fuel_tags:
                parts.append(f"연료={', '.join(conversation_fuel_tags)}")
            if beat_ladder:
                parts.append(f"beat={'; '.join(beat_ladder)}")
            state_variables = list(turn_continuation_contract.get("state_variables") or [])
            response_branches = dict(turn_continuation_contract.get("user_response_branches") or {})
            stall_breaker = str(turn_continuation_contract.get("stall_breaker") or "")
            scene_exit_condition = str(turn_continuation_contract.get("scene_exit_condition") or "")
            canon_safe_new_event_types = list(turn_continuation_contract.get("canon_safe_new_event_types") or [])
            if state_variables:
                parts.append(f"상태변수={'; '.join(state_variables[:2])}")
            branch_parts = [
                str(response_branches.get(key) or "")
                for key in ("short_or_ambiguous", "refuses_or_delays", "asks_question")
                if str(response_branches.get(key) or "")
            ][:2]
            if branch_parts:
                parts.append(f"분기={'; '.join(branch_parts)}")
            if stall_breaker:
                parts.append(f"정체해소={stall_breaker}")
            if scene_exit_condition:
                parts.append(f"퇴장조건={scene_exit_condition}")
            if canon_safe_new_event_types:
                parts.append(f"새사건유형={'; '.join(canon_safe_new_event_types[:2])}")
            must_not_reveal = list(knowledge_boundary.get("must_not_reveal") or [])
            can_hint = list(knowledge_boundary.get("can_hint") or [])
            if can_hint:
                parts.append(f"암시={'; '.join(can_hint[:2])}")
            if must_not_reveal:
                parts.append(f"금지공개={'; '.join(must_not_reveal[:2])}")
            if progression_seed:
                parts.append(f"진행={progression_seed}")
            if not parts:
                continue
            prefix = f"- {episode_no}화"
            scene_index = int(scene.get("scene_index") or 0)
            if scene_index > 0:
                prefix += f" 장면{scene_index}"
            for scope_key in sorted(scope_keys):
                scoped_parts = list(parts)
                participant_names = participant_names_by_scope.get(scope_key) or set()
                scoped_allowed_address_names = [
                    name
                    for name in allowed_address_names
                    if not participant_names or name in participant_names
                ]
                if scoped_allowed_address_names:
                    scoped_parts.append(f"허용호칭={'; '.join(scoped_allowed_address_names[:2])}")
                if must_not_address_as:
                    scoped_parts.append(f"금지호칭={'; '.join(must_not_address_as[:2])}")
                if surface_role_for_user:
                    scoped_parts.append(f"표면역할={surface_role_for_user}")
                if identity_spoiler_risk and identity_spoiler_risk != "unknown":
                    scoped_parts.append(f"정체위험={identity_spoiler_risk}")
                line = f"{prefix}: " + " | ".join(scoped_parts)
                lines = lines_by_scope.setdefault(scope_key, [])
                if len(lines) < limit_per_scope and line not in lines:
                    lines.append(line)
    return lines_by_scope


def load_character_chat_scene_context_lines_by_scope(conn, *, product_id: int) -> dict[str, list[str]]:
    if not hasattr(conn, "ping"):
        return {}
    with work_cursor(conn) as cur:
        return build_character_chat_scene_context_lines_by_scope(
            fetch_active_summary_rows(
                cur=cur,
                product_id=product_id,
                summary_type="episode_scene_extraction",
            )
        )


CHARACTER_CHAT_ASSET_READINESS_SUMMARY_TYPES = (
    "episode_summary",
    "episode_character_signals",
    "character_inventory_v3",
    "episode_scene_extraction",
    "character_rp_profile",
    "character_rp_examples",
)


def _summary_rows_by_scope(rows: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    scoped: dict[str, dict[str, object]] = {}
    for row in rows:
        scope_key = str(row.get("scope_key") or "").strip()
        if scope_key and scope_key not in scoped:
            scoped[scope_key] = row
    return scoped


def _summary_row_payload(row: dict[str, object]) -> dict[str, object]:
    payload = extract_json_object(str(row.get("summary_text") or "")) or {}
    return payload if isinstance(payload, dict) else {}


def _is_character_chat_profile_row_ready(
    row: dict[str, object] | None,
    *,
    scope_key: str,
) -> bool:
    payload = _summary_row_payload(row or {})
    return str(payload.get("character_key") or "").strip() == scope_key


def _is_character_chat_examples_row_ready(
    row: dict[str, object] | None,
    *,
    scope_key: str,
) -> bool:
    payload = _summary_row_payload(row or {})
    if str(payload.get("character_key") or "").strip() != scope_key:
        return False
    for item in list(payload.get("examples") or []):
        if not isinstance(item, dict):
            continue
        try:
            if int(item.get("episode_no") or 0) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _inventory_row_scope_key(row: dict[str, object], payload: dict[str, object]) -> str:
    return (
        str(row.get("scope_key") or "").strip()
        or str(payload.get("canonical_character_key") or "").strip()
        or str(payload.get("character_key") or "").strip()
    )


def _is_character_chat_public_candidate(payload: dict[str, object]) -> bool:
    readiness = dict(payload.get("chat_readiness_v1") or {})
    if str(readiness.get("exposure_decision") or "").strip() == "eligible":
        return True
    return bool(payload.get("public_chat_eligible")) or bool(readiness.get("character_chat_allowed"))


def _increment_reason(counter: dict[str, int], reason: str) -> None:
    counter[reason] = int(counter.get(reason) or 0) + 1


def _has_summary_row_for_inventory_alias(
    *,
    scope_key: str,
    inventory_payload: dict[str, object],
    rows_by_scope: dict[str, dict[str, object]],
) -> bool:
    alias_keys = build_inventory_scope_alias_keys(scope_key, inventory_payload) - {scope_key}
    return any(alias_key in rows_by_scope for alias_key in alias_keys)


def _is_character_chat_opening_row_ready(row: dict[str, object] | None, *, scope_key: str) -> bool:
    if not row:
        return False
    payload = _summary_row_payload(row)
    readiness = dict(payload.get("readiness") or {})
    if str(readiness.get("status") or "").strip() != "ready":
        return False
    chat_target = dict(payload.get("chat_target") or {})
    payload_scope_key = str(chat_target.get("scope_key") or "").strip()
    return normalize_character_chat_opening_payload(
        payload,
        scope_key=scope_key,
        display_name=str(chat_target.get("display_name") or ""),
    ) is not None and payload_scope_key == scope_key


def build_character_chat_asset_readiness_verification(
    *,
    product_id: int,
    summary_rows_by_type: dict[str, list[dict[str, object]]],
    story_context_status: str = "",
    total_episode_count: int = 0,
) -> dict[str, object]:
    """Verify that story-agent summaries are sufficient for character-chat exposure.

    Story context readiness only proves episode summaries exist. Character chat v2
    needs an exact-key inventory/profile/examples/episode-scene chain. The old global
    internal prompt and static opening are not runtime inputs because they are not
    bound to the reader's episode boundary.
    """
    rows_by_type = {
        summary_type: list(summary_rows_by_type.get(summary_type) or [])
        for summary_type in CHARACTER_CHAT_ASSET_READINESS_SUMMARY_TYPES
    }
    profile_rows_by_scope = _summary_rows_by_scope(rows_by_type["character_rp_profile"])
    example_rows_by_scope = _summary_rows_by_scope(rows_by_type["character_rp_examples"])
    scene_scope_keys = set(build_character_chat_scene_context_lines_by_scope(rows_by_type["episode_scene_extraction"]).keys())

    public_candidates: list[dict[str, object]] = []
    block_reason_counts: dict[str, int] = {}
    missing_profile_scope_keys: list[str] = []
    missing_examples_scope_keys: list[str] = []
    missing_internal_prompt_scope_keys: list[str] = []
    missing_opening_scope_keys: list[str] = []
    invalid_opening_scope_keys: list[str] = []
    missing_usable_scene_scope_keys: list[str] = []
    invalid_profile_scope_keys: list[str] = []
    invalid_examples_scope_keys: list[str] = []
    legacy_profile_scope_key_mismatch_scope_keys: list[str] = []
    legacy_examples_scope_key_mismatch_scope_keys: list[str] = []
    ready_scope_keys: list[str] = []
    public_slot_ready_scope_keys: list[str] = []
    main_protagonist_scope_keys: list[str] = []
    missing_main_protagonist_scope_keys: list[str] = []
    malformed_inventory_scope_keys: list[str] = []
    continuity_ambiguous_scope_keys: list[str] = []

    for row in rows_by_type["character_inventory_v3"]:
        payload = _summary_row_payload(row)
        scope_key = _inventory_row_scope_key(row, payload)
        if not scope_key:
            malformed_inventory_scope_keys.append(str(row.get("summary_id") or "unknown"))
            _increment_reason(block_reason_counts, "inventory_scope_key_missing")
            continue
        continuity_ambiguous = (
            str(payload.get("continuity_status") or "").strip() == "ambiguous"
            or "identity_continuity_ambiguous"
            in set(payload.get("identity_conflict_reasons") or [])
        )
        work_role = str(payload.get("work_role") or "").strip()
        is_main_protagonist = work_role == "main_protagonist"
        if continuity_ambiguous and (
            _is_character_chat_public_candidate(payload) or is_main_protagonist
        ):
            continuity_ambiguous_scope_keys.append(scope_key)
            _increment_reason(block_reason_counts, "identity_continuity_ambiguous")
        if not _is_character_chat_public_candidate(payload):
            continue

        if is_main_protagonist:
            main_protagonist_scope_keys.append(scope_key)

        missing_reasons: list[str] = []
        profile_row = profile_rows_by_scope.get(scope_key)
        if profile_row is None:
            missing_profile_scope_keys.append(scope_key)
            if _has_summary_row_for_inventory_alias(
                scope_key=scope_key,
                inventory_payload=payload,
                rows_by_scope=profile_rows_by_scope,
            ):
                legacy_profile_scope_key_mismatch_scope_keys.append(scope_key)
                missing_reasons.append("legacy_profile_scope_key_mismatch")
            else:
                missing_reasons.append("missing_profile")
        elif not _is_character_chat_profile_row_ready(profile_row, scope_key=scope_key):
            invalid_profile_scope_keys.append(scope_key)
            missing_reasons.append("invalid_profile_payload")

        examples_row = example_rows_by_scope.get(scope_key)
        if examples_row is None:
            missing_examples_scope_keys.append(scope_key)
            if _has_summary_row_for_inventory_alias(
                scope_key=scope_key,
                inventory_payload=payload,
                rows_by_scope=example_rows_by_scope,
            ):
                legacy_examples_scope_key_mismatch_scope_keys.append(scope_key)
                missing_reasons.append("legacy_examples_scope_key_mismatch")
            else:
                missing_reasons.append("missing_examples")
        elif not _is_character_chat_examples_row_ready(examples_row, scope_key=scope_key):
            invalid_examples_scope_keys.append(scope_key)
            missing_reasons.append("invalid_examples_payload")
        if scope_key not in scene_scope_keys:
            missing_usable_scene_scope_keys.append(scope_key)
            missing_reasons.append("missing_usable_scene")
        for reason in missing_reasons:
            _increment_reason(block_reason_counts, reason)
        if is_main_protagonist and missing_reasons:
            missing_main_protagonist_scope_keys.append(scope_key)

        if not missing_reasons:
            ready_scope_keys.append(scope_key)
            readiness = dict(payload.get("chat_readiness_v1") or {})
            if bool(payload.get("public_slot_eligible")) or bool(readiness.get("public_slot_allowed")):
                public_slot_ready_scope_keys.append(scope_key)

        public_candidates.append(
            {
                "scope_key": scope_key,
                "display_name": str(payload.get("display_name") or "").strip(),
                "work_role": work_role,
                "public_slot_eligible": bool(payload.get("public_slot_eligible")),
                "ready": not missing_reasons,
                "missing_reasons": missing_reasons,
            }
        )

    if malformed_inventory_scope_keys or continuity_ambiguous_scope_keys:
        character_chat_status = "failed"
    elif not public_candidates:
        character_chat_status = "none_eligible"
    elif missing_main_protagonist_scope_keys:
        character_chat_status = "hold"
    elif ready_scope_keys:
        character_chat_status = "ready"
    else:
        character_chat_status = "hold"

    return {
        "schema_version": "character_chat_asset_readiness_v2",
        "product_id": product_id,
        "story_context_status": story_context_status,
        "character_chat_status": character_chat_status,
        "total_episode_count": int(total_episode_count or 0),
        "summary_counts": {
            summary_type: len(rows)
            for summary_type, rows in rows_by_type.items()
        },
        "public_candidate_count": len(public_candidates),
        "ready_public_candidate_count": len(ready_scope_keys),
        "public_slot_ready_count": len(public_slot_ready_scope_keys),
        "ready_scope_keys": sorted(ready_scope_keys),
        "public_slot_ready_scope_keys": sorted(public_slot_ready_scope_keys),
        "main_protagonist_scope_keys": sorted(set(main_protagonist_scope_keys)),
        "missing_main_protagonist_scope_keys": sorted(set(missing_main_protagonist_scope_keys)),
        "missing_profile_scope_keys": sorted(set(missing_profile_scope_keys)),
        "missing_examples_scope_keys": sorted(set(missing_examples_scope_keys)),
        "missing_internal_prompt_scope_keys": sorted(set(missing_internal_prompt_scope_keys)),
        "missing_opening_scope_keys": sorted(set(missing_opening_scope_keys)),
        "invalid_opening_scope_keys": sorted(set(invalid_opening_scope_keys)),
        "missing_usable_scene_scope_keys": sorted(set(missing_usable_scene_scope_keys)),
        "invalid_profile_scope_keys": sorted(set(invalid_profile_scope_keys)),
        "invalid_examples_scope_keys": sorted(set(invalid_examples_scope_keys)),
        "legacy_profile_scope_key_mismatch_scope_keys": sorted(set(legacy_profile_scope_key_mismatch_scope_keys)),
        "legacy_examples_scope_key_mismatch_scope_keys": sorted(set(legacy_examples_scope_key_mismatch_scope_keys)),
        "malformed_inventory_scope_keys": sorted(set(malformed_inventory_scope_keys)),
        "continuity_ambiguous_scope_keys": sorted(set(continuity_ambiguous_scope_keys)),
        "block_reason_counts": dict(sorted(block_reason_counts.items())),
        "public_candidates": public_candidates[:20],
    }


def fetch_character_chat_asset_readiness_verification(
    cur,
    *,
    product_id: int,
    story_context_status: str = "",
    total_episode_count: int = 0,
) -> dict[str, object]:
    return build_character_chat_asset_readiness_verification(
        product_id=product_id,
        story_context_status=story_context_status,
        total_episode_count=total_episode_count,
        summary_rows_by_type={
            summary_type: fetch_active_summary_rows(
                cur=cur,
                product_id=product_id,
                summary_type=summary_type,
            )
            for summary_type in CHARACTER_CHAT_ASSET_READINESS_SUMMARY_TYPES
        },
    )


def is_character_chat_asset_readiness_actionable(
    readiness: dict[str, object] | None,
) -> bool:
    payload = dict(readiness or {})
    status = str(payload.get("character_chat_status") or "").strip()
    if status == "failed":
        return True
    if list(payload.get("continuity_ambiguous_scope_keys") or []):
        return True
    if list(payload.get("legacy_profile_scope_key_mismatch_scope_keys") or []):
        return True
    if list(payload.get("legacy_examples_scope_key_mismatch_scope_keys") or []):
        return True
    block_reason_counts = dict(payload.get("block_reason_counts") or {})
    if (
        int(block_reason_counts.get("legacy_profile_scope_key_mismatch") or 0) > 0
        or int(block_reason_counts.get("legacy_examples_scope_key_mismatch") or 0) > 0
    ):
        return True
    return status == "hold" and int(payload.get("public_candidate_count") or 0) > 0


def attach_character_chat_asset_readiness_to_status_row(cur, status_row: dict[str, object]) -> dict[str, object]:
    enriched = dict(status_row)
    product_id = int(enriched.get("product_id") or 0)
    if product_id <= 0:
        return enriched
    readiness = fetch_character_chat_asset_readiness_verification(
        cur,
        product_id=product_id,
        story_context_status=str(enriched.get("context_status") or ""),
        total_episode_count=int(enriched.get("total_episode_count") or 0),
    )
    enriched["character_chat_asset_readiness"] = readiness
    return enriched


def build_compound_summaries(cur, product_id: int, product_title: str) -> dict[str, tuple[int, int]]:
    counts = {
        "range": [0, 0],
        "product": [0, 0],
        "character": [0, 0],
    }
    episode_rows = fetch_active_summary_rows(cur=cur, product_id=product_id, summary_type="episode_summary")
    if not episode_rows:
        return {key: (value[0], value[1]) for key, value in counts.items()}

    episode_nos = [int(row.get("episode_from") or 0) for row in episode_rows if int(row.get("episode_from") or 0) > 0]
    desired_range_scope_keys: set[str] = set()
    for scope_key, start_episode, end_episode in build_range_scope_keys(episode_nos):
        desired_range_scope_keys.add(scope_key)
        scoped_rows = [
            row for row in episode_rows
            if start_episode <= int(row.get("episode_from") or 0) <= end_episode
        ]
        if not scoped_rows:
            continue
        upstream_components = [
            f"{int(row['summary_id'])}:{str(row['source_hash'])}"
            for row in scoped_rows
        ]
        source_hash = build_compound_summary_source_hash(RANGE_SUMMARY_FORMAT_VERSION, upstream_components)
        _, inserted = upsert_summary(
            cur,
            product_id=product_id,
            summary_type="range_summary",
            scope_key=scope_key,
            source_hash=source_hash,
            source_doc_count=len(scoped_rows),
            summary_text=build_range_summary_text(start_episode, end_episode, scoped_rows),
            episode_from=start_episode,
            episode_to=end_episode,
        )
        counts["range"][0 if inserted else 1] += 1

    deactivate_missing_active_scopes(cur, product_id, "range_summary", desired_range_scope_keys)

    range_rows_for_product = fetch_active_summary_rows(cur=cur, product_id=product_id, summary_type="range_summary")
    product_upstream_rows = range_rows_for_product or episode_rows
    product_upstream_components = [
        f"{int(row['summary_id'])}:{str(row['source_hash'])}"
        for row in product_upstream_rows
    ]
    product_summary_id, product_inserted = upsert_summary(
        cur,
        product_id=product_id,
        summary_type="product_summary",
        scope_key="product:all",
        source_hash=build_compound_summary_source_hash(PRODUCT_SUMMARY_FORMAT_VERSION, product_upstream_components),
        source_doc_count=len(product_upstream_rows),
        summary_text=build_product_summary_text(product_title=product_title, rows=product_upstream_rows),
        episode_from=min(episode_nos) if episode_nos else None,
        episode_to=max(episode_nos) if episode_nos else None,
    )
    counts["product"][0 if product_inserted else 1] += 1

    desired_character_scope_keys: set[str] = set()
    for candidate in extract_character_candidates(episode_rows):
        name = str(candidate["name"])
        scope_key = build_character_scope_key(name)
        desired_character_scope_keys.add(scope_key)
        supporting_rows = sorted(
            list(candidate["summary_rows"]),
            key=lambda row: (int(row.get("episode_from") or 0), int(row.get("summary_id") or 0)),
        )
        upstream_components = [
            f"{int(row['summary_id'])}:{str(row['source_hash'])}"
            for row in supporting_rows
        ]
        _, inserted = upsert_summary(
            cur,
            product_id=product_id,
            summary_type="character_snapshot",
            scope_key=scope_key,
            source_hash=build_compound_summary_source_hash(
                CHARACTER_SNAPSHOT_FORMAT_VERSION,
                [name, *upstream_components],
            ),
            source_doc_count=len(supporting_rows),
            summary_text=build_character_snapshot_text(name=name, candidate=candidate),
            episode_from=min(int(item) for item in set(candidate["episode_nos"])),
            episode_to=max(int(item) for item in set(candidate["episode_nos"])),
        )
        counts["character"][0 if inserted else 1] += 1

    deactivate_missing_active_scopes(cur, product_id, "character_snapshot", desired_character_scope_keys)

    return {key: (value[0], value[1]) for key, value in counts.items()}


def build_compound_summaries_delta(
    cur,
    *,
    product_id: int,
    product_title: str,
    touched_range_scopes: Iterable[tuple[str, int, int]],
) -> dict[str, tuple[int, int]]:
    counts = {
        "range": [0, 0],
        "product": [0, 0],
    }
    episode_rows = fetch_active_summary_rows(cur=cur, product_id=product_id, summary_type="episode_summary")
    if not episode_rows:
        return {key: (value[0], value[1]) for key, value in counts.items()}

    for scope_key, start_episode, end_episode in list(touched_range_scopes):
        scoped_rows = [
            row for row in episode_rows
            if start_episode <= int(row.get("episode_from") or 0) <= end_episode
        ]
        if not scoped_rows:
            continue
        upstream_components = [
            f"{int(row['summary_id'])}:{str(row['source_hash'])}"
            for row in scoped_rows
        ]
        range_summary_text = build_range_summary_text(start_episode, end_episode, scoped_rows)
        is_valid, reason = validate_compound_summary_text("range_summary", range_summary_text)
        if not is_valid:
            logger.warning(
                "story_agent_delta_range_summary_skip product_id=%s scope_key=%s reason=%s",
                product_id,
                scope_key,
                reason,
            )
            counts["range"][1] += 1
            continue
        _, inserted = upsert_summary(
            cur,
            product_id=product_id,
            summary_type="range_summary",
            scope_key=scope_key,
            source_hash=build_compound_summary_source_hash(RANGE_SUMMARY_FORMAT_VERSION, upstream_components),
            source_doc_count=len(scoped_rows),
            summary_text=range_summary_text,
            episode_from=start_episode,
            episode_to=end_episode,
        )
        counts["range"][0 if inserted else 1] += 1

    range_rows_for_product = fetch_active_summary_rows(cur=cur, product_id=product_id, summary_type="range_summary")
    product_upstream_rows = range_rows_for_product or episode_rows
    product_upstream_components = [
        f"{int(row['summary_id'])}:{str(row['source_hash'])}"
        for row in product_upstream_rows
    ]
    product_summary_text = build_product_summary_text(product_title=product_title, rows=product_upstream_rows)
    is_valid, reason = validate_compound_summary_text("product_summary", product_summary_text)
    if not is_valid:
        logger.warning(
            "story_agent_delta_product_summary_skip product_id=%s reason=%s",
            product_id,
            reason,
        )
        counts["product"][1] += 1
        return {key: (value[0], value[1]) for key, value in counts.items()}
    _, inserted = upsert_summary(
        cur,
        product_id=product_id,
        summary_type="product_summary",
        scope_key="product:all",
        source_hash=build_compound_summary_source_hash(PRODUCT_SUMMARY_FORMAT_VERSION, product_upstream_components),
        source_doc_count=len(product_upstream_rows),
        summary_text=product_summary_text,
        episode_from=min(int(row.get("episode_from") or 0) for row in product_upstream_rows if int(row.get("episode_from") or 0) > 0) if product_upstream_rows else None,
        episode_to=max(int(row.get("episode_to") or 0) for row in product_upstream_rows if int(row.get("episode_to") or 0) > 0) if product_upstream_rows else None,
    )
    counts["product"][0 if inserted else 1] += 1
    return {key: (value[0], value[1]) for key, value in counts.items()}


async def download_epub_binary(file_name: str) -> bytes | None:
    presigned_url = comm_service.make_r2_presigned_url(
        type="download",
        bucket_name=settings.R2_SC_EPUB_BUCKET,
        file_id=file_name,
    )
    try:
        async with AsyncClient(timeout=120.0) as client:
            response = await client.get(presigned_url)
            response.raise_for_status()
            return response.content
    except (HTTPStatusError, RequestError):
        return None


async def resolve_source_payload(row: dict, use_epub_fallback: bool) -> dict[str, str] | None:
    episode_content = str(row.get("episode_content") or "").strip()
    if episode_content:
        return {
            "source_type": "episode_content",
            "source_locator": f"episode:{row['episode_id']}",
            "html_content": episode_content,
        }

    if not use_epub_fallback:
        return None

    file_name = row.get("file_name")
    if not file_name:
        return None

    epub_binary = await download_epub_binary(str(file_name))
    if epub_binary is None:
        return None

    payload = _extract_epub_payload_from_epub(epub_binary)
    html_content = str(payload.get("html_content") or "").strip()
    if not html_content:
        return None

    return {
        "source_type": "epub_fallback",
        "source_locator": str(file_name),
        "html_content": html_content,
    }


def fetch_existing_doc(cur, episode_id: int, source_hash: str, source_type: str) -> dict | None:
    cur.execute(
        """
        SELECT context_doc_id, version_no, is_active
          FROM tb_story_agent_context_doc
         WHERE episode_id = %s
           AND source_hash = %s
           AND source_type = %s
         LIMIT 1
        """,
        (episode_id, source_hash, source_type),
    )
    return cur.fetchone()


def fetch_next_version_no(cur, episode_id: int) -> int:
    cur.execute(
        """
        SELECT COALESCE(MAX(version_no), 0) AS max_version_no
          FROM tb_story_agent_context_doc
         WHERE episode_id = %s
        """,
        (episode_id,),
    )
    row = cur.fetchone() or {}
    return int(row.get("max_version_no") or 0) + 1


def fetch_existing_summary(cur, product_id: int, summary_type: str, scope_key: str, source_hash: str) -> dict | None:
    cur.execute(
        """
        SELECT summary_id, version_no, is_active, summary_text
          FROM tb_story_agent_context_summary
         WHERE product_id = %s
           AND summary_type = %s
           AND scope_key = %s
           AND source_hash = %s
         ORDER BY is_active DESC, summary_id DESC
         LIMIT 1
        """,
        (product_id, summary_type, scope_key, source_hash),
    )
    return cur.fetchone()


def fetch_active_summary_by_scope(
    cur,
    *,
    product_id: int,
    summary_type: str,
    scope_key: str,
) -> dict | None:
    cur.execute(
        """
        SELECT summary_id, version_no, is_active, source_hash, summary_text
          FROM tb_story_agent_context_summary
         WHERE product_id = %s
           AND summary_type = %s
           AND scope_key = %s
           AND is_active = 'Y'
         ORDER BY summary_id DESC
         LIMIT 1
        """,
        (product_id, summary_type, scope_key),
    )
    return cur.fetchone()


def fetch_next_summary_version_no(cur, product_id: int, summary_type: str, scope_key: str) -> int:
    cur.execute(
        """
        SELECT COALESCE(MAX(version_no), 0) AS max_version_no
          FROM tb_story_agent_context_summary
         WHERE product_id = %s
           AND summary_type = %s
           AND scope_key = %s
        """,
        (product_id, summary_type, scope_key),
    )
    row = cur.fetchone() or {}
    return int(row.get("max_version_no") or 0) + 1


def activate_existing_summary(cur, summary_id: int, product_id: int, summary_type: str, scope_key: str) -> None:
    cur.execute(
        """
        UPDATE tb_story_agent_context_summary
           SET is_active = 'N'
         WHERE product_id = %s
           AND summary_type = %s
           AND scope_key = %s
           AND is_active = 'Y'
           AND summary_id <> %s
        """,
        (product_id, summary_type, scope_key, summary_id),
    )
    cur.execute(
        """
        UPDATE tb_story_agent_context_summary
           SET is_active = 'Y'
         WHERE summary_id = %s
        """,
        (summary_id,),
    )


def update_existing_summary_payload(
    cur,
    *,
    summary_id: int,
    product_id: int,
    summary_type: str,
    scope_key: str,
    source_doc_count: int,
    summary_text: str,
    episode_from: int | None = None,
    episode_to: int | None = None,
) -> None:
    cur.execute(
        """
        UPDATE tb_story_agent_context_summary
           SET is_active = 'N'
         WHERE product_id = %s
           AND summary_type = %s
           AND scope_key = %s
           AND is_active = 'Y'
           AND summary_id <> %s
        """,
        (product_id, summary_type, scope_key, summary_id),
    )
    cur.execute(
        """
        UPDATE tb_story_agent_context_summary
           SET source_doc_count = %s,
               episode_from = %s,
               episode_to = %s,
               summary_text = %s,
               is_active = 'Y'
         WHERE summary_id = %s
        """,
        (source_doc_count, episode_from, episode_to, summary_text, summary_id),
    )


def activate_existing_doc(cur, episode_id: int, context_doc_id: int) -> None:
    cur.execute(
        """
        UPDATE tb_story_agent_context_doc
           SET is_active = 'N'
         WHERE episode_id = %s
           AND is_active = 'Y'
           AND context_doc_id <> %s
        """,
        (episode_id, context_doc_id),
    )
    cur.execute(
        """
        UPDATE tb_story_agent_context_doc
           SET is_active = 'Y'
         WHERE context_doc_id = %s
        """,
        (context_doc_id,),
    )


def insert_doc_and_chunks(cur, row: dict, source: dict[str, str], normalized_text: str, chunks: list[dict[str, object]]) -> int:
    source_hash = sha256_text(normalized_text)
    existing = fetch_existing_doc(
        cur=cur,
        episode_id=int(row["episode_id"]),
        source_hash=source_hash,
        source_type=str(source["source_type"]),
    )
    if existing:
        activate_existing_doc(cur, int(row["episode_id"]), int(existing["context_doc_id"]))
        return int(existing["context_doc_id"])

    version_no = fetch_next_version_no(cur, int(row["episode_id"]))
    cur.execute(
        """
        UPDATE tb_story_agent_context_doc
           SET is_active = 'N'
         WHERE episode_id = %s
           AND is_active = 'Y'
        """,
        (int(row["episode_id"]),),
    )
    cur.execute(
        """
        INSERT INTO tb_story_agent_context_doc (
            product_id,
            episode_id,
            episode_no,
            source_type,
            source_locator,
            source_hash,
            source_text_length,
            version_no,
            is_active,
            created_id
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'Y', %s)
        """,
        (
            int(row["product_id"]),
            int(row["episode_id"]),
            int(row["episode_no"]),
            str(source["source_type"]),
            str(source["source_locator"]),
            source_hash,
            len(normalized_text),
            version_no,
            settings.DB_DML_DEFAULT_ID,
        ),
    )
    context_doc_id = int(cur.lastrowid)

    cur.executemany(
        """
        INSERT INTO tb_story_agent_context_chunk (
            context_doc_id,
            product_id,
            episode_id,
            episode_no,
            chunk_no,
            text_hash,
            char_start,
            char_end,
            text,
            created_id
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        [
            (
                context_doc_id,
                int(row["product_id"]),
                int(row["episode_id"]),
                int(row["episode_no"]),
                int(chunk["chunk_no"]),
                str(chunk["text_hash"]),
                int(chunk["char_start"]),
                int(chunk["char_end"]),
                str(chunk["text"]),
                settings.DB_DML_DEFAULT_ID,
            )
            for chunk in chunks
        ],
    )
    return context_doc_id


async def insert_episode_summary(
    conn,
    row: dict,
    source_hash: str,
    normalized_text: str,
    *,
    summary_client: AsyncClient | None,
    verbose: bool = False,
) -> tuple[int, bool, dict[str, object]]:
    product_id = int(row["product_id"])
    episode_id = int(row["episode_id"])
    episode_no = int(row["episode_no"])
    scope_key = f"episode:{episode_id}"
    summary_type = "episode_summary"
    summary_source_hash = build_summary_source_hash(source_hash, str(row.get("episode_title") or ""))

    with work_cursor(conn) as cur:
        existing = fetch_existing_summary(
            cur=cur,
            product_id=product_id,
            summary_type=summary_type,
            scope_key=scope_key,
            source_hash=summary_source_hash,
        )
    if existing:
        with work_cursor(conn) as cur:
            activate_existing_summary(cur, int(existing["summary_id"]), product_id, summary_type, scope_key)
        conn.commit()
        return int(existing["summary_id"]), False, {
            "used_llm": False,
            "retry_count": 0,
            "fallback_used": False,
            "fallback_reason": "",
        }

    summary_text, summary_meta = await generate_episode_summary_text(
        client=summary_client,
        row=row,
        normalized_text=normalized_text,
        verbose=verbose,
    )
    with work_cursor(conn) as cur:
        summary_id, inserted = upsert_summary(
            cur,
            product_id=product_id,
            summary_type=summary_type,
            scope_key=scope_key,
            source_hash=summary_source_hash,
            source_doc_count=1,
            summary_text=summary_text,
            episode_from=episode_no,
            episode_to=episode_no,
        )
    conn.commit()
    return int(summary_id), inserted, summary_meta


def refresh_product_context_status(cur, product_id: int, total_episode_count: int) -> dict[str, object]:
    cur.execute(
        """
        SELECT COUNT(*) AS ready_episode_count
          FROM tb_story_agent_context_summary
         WHERE product_id = %s
           AND summary_type = 'episode_summary'
           AND is_active = 'Y'
        """,
        (product_id,),
    )
    row = cur.fetchone() or {}
    ready_episode_count = int(row.get("ready_episode_count") or 0)

    if ready_episode_count <= 0:
        context_status = "pending"
    elif ready_episode_count < total_episode_count:
        context_status = "processing"
    else:
        context_status = "ready"

    cur.execute(
        """
        INSERT INTO tb_story_agent_context_product (
            product_id,
            context_status,
            total_episode_count,
            ready_episode_count,
            last_built_at,
            last_error_message,
            created_id,
            updated_id
        ) VALUES (%s, %s, %s, %s, NOW(), NULL, %s, %s)
        ON DUPLICATE KEY UPDATE
            context_status = IF(context_status = 'disabled', context_status, VALUES(context_status)),
            total_episode_count = VALUES(total_episode_count),
            ready_episode_count = VALUES(ready_episode_count),
            last_built_at = VALUES(last_built_at),
            last_error_message = IF(context_status = 'disabled', last_error_message, NULL),
            updated_id = VALUES(updated_id)
        """,
        (
            product_id,
            context_status,
            total_episode_count,
            ready_episode_count,
            settings.DB_DML_DEFAULT_ID,
            settings.DB_DML_DEFAULT_ID,
        ),
    )
    return {
        "product_id": product_id,
        "context_status": context_status,
        "total_episode_count": total_episode_count,
        "ready_episode_count": ready_episode_count,
    }


def assert_story_agent_foundation_invariants(cur, *, product_id: int) -> None:
    cur.execute(
        """
        SELECT summary_type, COUNT(*) AS cnt
          FROM tb_story_agent_context_summary
         WHERE product_id = %s
           AND is_active = 'Y'
           AND summary_type IN ('episode_summary', 'episode_character_signals', 'character_inventory', 'character_inventory_v3')
         GROUP BY summary_type
        """,
        (product_id,),
    )
    counts = {str(row.get("summary_type") or ""): int(row.get("cnt") or 0) for row in list(cur.fetchall() or [])}
    episode_summary_count = int(counts.get("episode_summary") or 0)
    signal_count = int(counts.get("episode_character_signals") or 0)
    inventory_count = int(counts.get("character_inventory") or 0)
    inventory_v3_count = int(counts.get("character_inventory_v3") or 0)

    if episode_summary_count > 0 and signal_count != episode_summary_count:
        raise ValueError(
            f"story-agent foundation mismatch: product_id={product_id} "
            f"episode_summary={episode_summary_count} episode_character_signals={signal_count}"
        )
    if signal_count > 0 and inventory_count <= 0:
        raise ValueError(
            f"story-agent foundation mismatch: product_id={product_id} "
            f"episode_character_signals={signal_count} character_inventory={inventory_count}"
        )
    if signal_count > 0 and inventory_v3_count <= 0:
        raise ValueError(
            f"story-agent foundation mismatch: product_id={product_id} "
            f"episode_character_signals={signal_count} character_inventory_v3={inventory_v3_count}"
        )


def fetch_total_episode_count(cur, product_id: int) -> int:
    cur.execute(
        """
        SELECT COUNT(*) AS total_episode_count
          FROM tb_product p
          JOIN tb_product_episode pe
            ON pe.product_id = p.product_id
         WHERE p.product_id = %s
           AND p.price_type IN ('free', 'paid')
           AND p.status_code = 'ongoing'
           AND pe.use_yn = 'Y'
           AND pe.open_yn = 'Y'
        """,
        (product_id,),
    )
    row = cur.fetchone() or {}
    return int(row.get("total_episode_count") or 0)


def fetch_product_context_status(cur, *, product_id: int) -> str:
    cur.execute(
        """
        SELECT context_status
          FROM tb_story_agent_context_product
         WHERE product_id = %s
        """,
        (product_id,),
    )
    row = cur.fetchone() or {}
    return str(row.get("context_status") or "").strip()


def mark_product_context_failed(*, product_id: int, total_episode_count: int, error_message: str) -> int:
    conn = db_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS ready_episode_count
                  FROM tb_story_agent_context_summary
                 WHERE product_id = %s
                   AND summary_type = 'episode_summary'
                   AND is_active = 'Y'
                """,
                (product_id,),
            )
            ready_row = cur.fetchone() or {}
            ready_episode_count = int(ready_row.get("ready_episode_count") or 0)
            cur.execute(
                """
                INSERT INTO tb_story_agent_context_product (
                    product_id,
                    context_status,
                    total_episode_count,
                    ready_episode_count,
                    last_error_message,
                    created_id,
                    updated_id
                ) VALUES (%s, 'failed', %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    context_status = IF(context_status IN ('disabled', 'ready'), context_status, 'failed'),
                    total_episode_count = VALUES(total_episode_count),
                    ready_episode_count = VALUES(ready_episode_count),
                    last_error_message = IF(context_status = 'disabled', last_error_message, VALUES(last_error_message)),
                    updated_id = VALUES(updated_id)
                """,
                (
                    product_id,
                    total_episode_count,
                    ready_episode_count,
                    error_message[:500],
                    settings.DB_DML_DEFAULT_ID,
                    settings.DB_DML_DEFAULT_ID,
                ),
            )
        conn.commit()
        return ready_episode_count
    finally:
        conn.close()


def repair_failed_delta_context_statuses(cur, rows: Iterable[dict]) -> list[dict[str, object]]:
    rows_by_product: dict[int, list[dict]] = {}
    for row in rows:
        rows_by_product.setdefault(int(row["product_id"]), []).append(row)

    repaired_products: list[dict[str, object]] = []
    for product_id, product_rows in sorted(rows_by_product.items()):
        if fetch_product_context_status(cur, product_id=product_id) != "failed":
            continue
        if build_open_add_episode_id_set(cur, product_id=product_id, product_rows=product_rows):
            continue
        if build_signal_repair_episode_id_set(cur, product_id=product_id, product_rows=product_rows):
            continue
        try:
            assert_story_agent_foundation_invariants(cur, product_id=product_id)
        except ValueError as exc:
            logger.warning(
                "story_agent_delta_status_repair_skip product_id=%s reason=%s",
                product_id,
                str(exc)[:200],
            )
            continue

        total_episode_count = fetch_total_episode_count(cur, product_id=product_id)
        status_row = refresh_product_context_status(
            cur,
            product_id=product_id,
            total_episode_count=total_episode_count,
        )
        logger.info(
            "story_agent_delta_status_repair product_id=%s status=%s ready=%s total=%s",
            product_id,
            status_row.get("context_status"),
            status_row.get("ready_episode_count"),
            status_row.get("total_episode_count"),
        )
        repaired_products.append(status_row)
    return repaired_products


def build_character_chat_asset_repair_plan(
    readiness: dict[str, object] | None,
) -> dict[str, object]:
    payload = dict(readiness or {})
    blocked_scope_keys = {
        str(scope_key or "").strip()
        for scope_key in list(payload.get("continuity_ambiguous_scope_keys") or [])
        if str(scope_key or "").strip()
    }
    rp_scope_keys = {
        str(scope_key or "").strip()
        for field_name in (
            "missing_profile_scope_keys",
            "missing_examples_scope_keys",
            "invalid_profile_scope_keys",
            "invalid_examples_scope_keys",
            "legacy_profile_scope_key_mismatch_scope_keys",
            "legacy_examples_scope_key_mismatch_scope_keys",
        )
        for scope_key in list(payload.get(field_name) or [])
        if str(scope_key or "").strip()
    } - blocked_scope_keys
    scene_scope_keys = {
        str(scope_key or "").strip()
        for scope_key in list(payload.get("missing_usable_scene_scope_keys") or [])
        if str(scope_key or "").strip()
    } - blocked_scope_keys
    return {
        "rp_scope_keys": sorted(rp_scope_keys),
        "scene_scope_keys": sorted(scene_scope_keys),
        "blocked_scope_keys": sorted(blocked_scope_keys),
        "repairable": bool(rp_scope_keys or scene_scope_keys),
    }


def select_character_chat_scene_repair_rows(
    *,
    inventory_map: dict[str, dict[str, object]],
    episode_summary_rows: list[dict[str, object]],
    scene_scope_keys: set[str],
    limit: int,
) -> tuple[list[dict[str, object]], dict[int, set[str]]]:
    episode_rows_by_no = {
        int(row.get("episode_from") or row.get("episode_no") or 0): row
        for row in episode_summary_rows
        if int(row.get("episode_from") or row.get("episode_no") or 0) > 0
    }
    required_scope_keys_by_episode_no: dict[int, set[str]] = {}
    ordered_scope_keys = sorted(
        scene_scope_keys,
        key=lambda scope_key: (
            0
            if str(dict(inventory_map.get(scope_key) or {}).get("work_role") or "")
            == "main_protagonist"
            else 1,
            scope_key,
        ),
    )
    max_rows = max(int(limit or 0), 1)
    for scope_key in ordered_scope_keys:
        inventory_item = dict(inventory_map.get(scope_key) or {})
        evidence_episode_nos = sorted(
            {
                int(value)
                for value in list(inventory_item.get("evidence_episode_nos") or [])
                if int(value) in episode_rows_by_no
            },
            reverse=True,
        )
        if not evidence_episode_nos:
            fallback_episode_no = int(
                inventory_item.get("latest_seen_episode_no")
                or inventory_item.get("first_seen_episode_no")
                or 0
            )
            if fallback_episode_no in episode_rows_by_no:
                evidence_episode_nos = [fallback_episode_no]
        for episode_no in evidence_episode_nos[:1]:
            if (
                episode_no not in required_scope_keys_by_episode_no
                and len(required_scope_keys_by_episode_no) >= max_rows
            ):
                continue
            required_scope_keys_by_episode_no.setdefault(episode_no, set()).add(
                scope_key
            )
    selected_rows = [
        episode_rows_by_no[episode_no]
        for episode_no in sorted(required_scope_keys_by_episode_no)
    ]
    return selected_rows, required_scope_keys_by_episode_no


def touch_product_context_build_attempt(cur, *, product_id: int) -> None:
    cur.execute(
        """
        INSERT INTO tb_story_agent_context_product (
            product_id,
            context_status,
            total_episode_count,
            ready_episode_count,
            last_built_at,
            created_id,
            updated_id
        ) VALUES (%s, 'pending', 0, 0, NOW(), %s, %s)
        ON DUPLICATE KEY UPDATE
            last_built_at = IF(context_status = 'disabled', last_built_at, VALUES(last_built_at)),
            updated_id = IF(context_status = 'disabled', updated_id, VALUES(updated_id))
        """,
        (
            product_id,
            settings.DB_DML_DEFAULT_ID,
            settings.DB_DML_DEFAULT_ID,
        ),
    )


async def repair_character_chat_assets(
    *,
    rows: Iterable[dict],
    args: argparse.Namespace,
    results: dict[str, object],
) -> None:
    product_results = results.setdefault("products", [])
    repair_records = results.setdefault("character_asset_repairs", [])
    if not isinstance(product_results, list) or not isinstance(repair_records, list):
        raise TypeError("story-agent repair results must contain list fields")
    rows_by_product: dict[int, list[dict]] = {}
    for row in rows:
        rows_by_product.setdefault(int(row["product_id"]), []).append(row)
    if not rows_by_product:
        return

    summary_client: AsyncClient | None = None
    if (
        (OPENROUTER_API_KEY and RP_OPENROUTER_MODEL)
        or (OPENROUTER_API_KEY and EPISODE_SCENE_EXTRACTION_OPENROUTER_MODEL)
        or (settings.ANTHROPIC_API_KEY and RP_REASONING_MODEL)
    ):
        summary_client = AsyncClient(timeout=EPISODE_SUMMARY_TIMEOUT_SECONDS)

    work_conn = db_connect()
    try:
        for product_id, product_rows in sorted(rows_by_product.items()):
            results["character_asset_repair_attempted"] += 1
            repair_record: dict[str, object] = {"product_id": product_id}
            try:
                with product_lock_connection(product_id) if args.apply else nullcontext(None) as lock_conn:
                    if args.apply and lock_conn is None:
                        repair_record["status"] = "locked"
                        results["character_asset_repair_no_progress"] += 1
                        repair_records.append(repair_record)
                        continue

                    with work_cursor(work_conn) as cur:
                        total_episode_count = fetch_total_episode_count(
                            cur,
                            product_id=product_id,
                        )
                        context_status = fetch_product_context_status(
                            cur,
                            product_id=product_id,
                        )
                        ready_episode_count = fetch_product_ready_episode_count(
                            cur,
                            product_id=product_id,
                        )
                        before_readiness = fetch_character_chat_asset_readiness_verification(
                            cur,
                            product_id=product_id,
                            story_context_status=context_status,
                            total_episode_count=total_episode_count,
                        )
                        inventory_map = fetch_active_character_inventory_map(
                            cur=cur,
                            product_id=product_id,
                            summary_type="character_inventory_v3",
                        )
                        episode_summary_rows = fetch_active_summary_rows(
                            cur=cur,
                            product_id=product_id,
                            summary_type="episode_summary",
                        )
                        episode_texts_by_no = fetch_active_episode_texts_by_no(
                            cur,
                            product_id=product_id,
                        )
                        relation_map = build_canonical_relation_inventory_map(
                            relation_map=fetch_active_relation_inventory_map(
                                cur=cur,
                                product_id=product_id,
                            ),
                            inventory_map=inventory_map,
                        )
                        historical_inventory_state_map = (
                            fetch_rp_ready_character_inventory_history_state_map(
                                cur,
                                product_id=product_id,
                            )
                        )

                    repair_plan = build_character_chat_asset_repair_plan(
                        before_readiness
                    )
                    scene_scope_keys = set(repair_plan["scene_scope_keys"])
                    scene_rows, required_scope_keys_by_episode_no = (
                        select_character_chat_scene_repair_rows(
                            inventory_map=inventory_map,
                            episode_summary_rows=episode_summary_rows,
                            scene_scope_keys=scene_scope_keys,
                            limit=int(getattr(args, "max_delta_episodes", 0) or 0),
                        )
                    )
                    scene_counts = (0, 0)
                    if scene_rows:
                        scene_counts = await build_episode_scene_extraction_summaries(
                            conn=work_conn,
                            product_id=product_id,
                            product_title=str(product_rows[0].get("title") or ""),
                            episode_rows=scene_rows,
                            episode_texts_by_no=episode_texts_by_no,
                            summary_client=summary_client,
                            canonical_character_packet=build_episode_scene_canonical_character_packet(
                                inventory_map
                            ),
                            required_scope_keys_by_episode_no=required_scope_keys_by_episode_no,
                            cleanup_missing_scopes=False,
                            raise_unexpected_errors=True,
                            verbose=args.verbose,
                        )
                        results["inserted_episode_scene_extractions"] += scene_counts[0]
                        results["reused_episode_scene_extractions"] += scene_counts[1]

                    rp_counts = await build_rp_summaries_delta(
                        conn=work_conn,
                        product_id=product_id,
                        affected_scope_keys=set(repair_plan["rp_scope_keys"]),
                        episode_rows=episode_summary_rows,
                        episode_texts_by_no=episode_texts_by_no,
                        summary_client=summary_client,
                        inventory_map=inventory_map,
                        relation_map=relation_map,
                        historical_inventory_state_map=historical_inventory_state_map,
                        raise_unexpected_errors=True,
                        verbose=args.verbose,
                    )
                    results["inserted_character_rp_profiles"] += int(
                        (rp_counts.get("profile") or (0, 0))[0]
                    )
                    results["reused_character_rp_profiles"] += int(
                        (rp_counts.get("profile") or (0, 0))[1]
                    )
                    results["inserted_character_rp_examples"] += int(
                        (rp_counts.get("examples") or (0, 0))[0]
                    )
                    results["reused_character_rp_examples"] += int(
                        (rp_counts.get("examples") or (0, 0))[1]
                    )

                    with work_cursor(work_conn) as cur:
                        after_readiness = fetch_character_chat_asset_readiness_verification(
                            cur,
                            product_id=product_id,
                            story_context_status=context_status,
                            total_episode_count=total_episode_count,
                        )
                        touch_product_context_build_attempt(
                            cur,
                            product_id=product_id,
                        )
                    work_conn.commit()

                    recovered = (
                        is_character_chat_asset_readiness_actionable(before_readiness)
                        and not is_character_chat_asset_readiness_actionable(after_readiness)
                    )
                    results[
                        "character_asset_repair_recovered"
                        if recovered
                        else "character_asset_repair_no_progress"
                    ] += 1
                    repair_record.update(
                        {
                            "status": "recovered" if recovered else "no_progress",
                            "before_status": str(
                                before_readiness.get("character_chat_status") or ""
                            ),
                            "after_status": str(
                                after_readiness.get("character_chat_status") or ""
                            ),
                            "rp_scope_keys": list(repair_plan["rp_scope_keys"]),
                            "scene_scope_keys": list(repair_plan["scene_scope_keys"]),
                            "blocked_scope_keys": list(
                                repair_plan["blocked_scope_keys"]
                            ),
                        }
                    )
                    product_result = {
                        "product_id": product_id,
                        "context_status": context_status,
                        "total_episode_count": total_episode_count,
                        "ready_episode_count": ready_episode_count,
                        "character_chat_asset_readiness": after_readiness,
                        "character_asset_repair": repair_record,
                    }
                    existing_product = next(
                        (
                            item
                            for item in product_results
                            if int(dict(item or {}).get("product_id") or 0)
                            == product_id
                        ),
                        None,
                    )
                    if existing_product is None:
                        product_results.append(product_result)
                    else:
                        existing_product.update(product_result)
                    repair_records.append(repair_record)
                    logger.info(
                        "story_agent_character_asset_repair product_id=%s status=%s rp_scopes=%s scene_scopes=%s",
                        product_id,
                        repair_record["status"],
                        len(list(repair_plan["rp_scope_keys"])),
                        len(list(repair_plan["scene_scope_keys"])),
                    )
            except Exception as exc:
                try:
                    work_conn.rollback()
                except Exception:
                    pass
                try:
                    with work_cursor(work_conn) as cur:
                        touch_product_context_build_attempt(
                            cur,
                            product_id=product_id,
                        )
                    work_conn.commit()
                except Exception:
                    try:
                        work_conn.rollback()
                    except Exception:
                        pass
                results["character_asset_repair_failed"] += 1
                repair_record.update(
                    {"status": "failed", "error": str(exc)[:240]}
                )
                repair_records.append(repair_record)
                logger.exception(
                    "story_agent_character_asset_repair_failed product_id=%s error=%s",
                    product_id,
                    str(exc)[:240],
                )
    finally:
        if summary_client is not None:
            await summary_client.aclose()
        work_conn.close()


def build_delta_exit_code(results: dict[str, object], *, apply: bool) -> int:
    if not apply:
        return 0
    for product in list(results.get("products") or []):
        if str((product or {}).get("context_status") or "").strip() == "failed":
            return 1
    return int(int(results.get("character_asset_repair_failed") or 0) > 0)


def build_empty_results() -> dict[str, object]:
    return {
        "inserted_docs": 0,
        "reused_docs": 0,
        "inserted_summaries": 0,
        "reused_summaries": 0,
        "llm_generated_summaries": 0,
        "summary_retry_successes": 0,
        "summary_fallbacks": 0,
        "inserted_range_summaries": 0,
        "reused_range_summaries": 0,
        "inserted_product_summaries": 0,
        "reused_product_summaries": 0,
        "inserted_character_snapshots": 0,
        "reused_character_snapshots": 0,
        "inserted_episode_character_signals": 0,
        "reused_episode_character_signals": 0,
        "inserted_episode_scene_extractions": 0,
        "reused_episode_scene_extractions": 0,
        "inserted_character_inventories": 0,
        "reused_character_inventories": 0,
        "inserted_character_inventory_v3": 0,
        "reused_character_inventory_v3": 0,
        "inserted_relation_inventories": 0,
        "reused_relation_inventories": 0,
        "inserted_character_rp_profiles": 0,
        "reused_character_rp_profiles": 0,
        "inserted_character_rp_examples": 0,
        "reused_character_rp_examples": 0,
        "inserted_character_chat_openings": 0,
        "reused_character_chat_openings": 0,
        "character_asset_repair_attempted": 0,
        "character_asset_repair_recovered": 0,
        "character_asset_repair_no_progress": 0,
        "character_asset_repair_failed": 0,
        "character_asset_repairs": [],
        "skipped_rows": 0,
        "products": [],
        "delta_verifications": [],
    }


def select_full_build_episode_rows(
    *,
    product_rows: list[dict],
    episode_summary_rows: list[dict],
    args: argparse.Namespace,
) -> tuple[list[dict], bool]:
    is_partial_build = bool(
        getattr(args, "episode_ids", None)
        or getattr(args, "episode_nos", None)
        or int(getattr(args, "limit", 0) or 0) > 0
    )
    if not is_partial_build:
        return episode_summary_rows, True

    selected_episode_ids = {
        int(row.get("episode_id") or 0)
        for row in product_rows
        if int(row.get("episode_id") or 0) > 0
    }
    selected_episode_nos = {
        int(row.get("episode_no") or 0)
        for row in product_rows
        if int(row.get("episode_no") or 0) > 0
    }
    selected_rows = [
        row
        for row in episode_summary_rows
        if (
            str(row.get("scope_key") or "").removeprefix("episode:").isdigit()
            and int(str(row.get("scope_key") or "").removeprefix("episode:")) in selected_episode_ids
        )
        or int(row.get("episode_from") or 0) in selected_episode_nos
    ]
    return selected_rows, False


async def build_context_rows(rows: Iterable[dict], args: argparse.Namespace) -> dict[str, object]:
    results = build_empty_results()

    rows_by_product: dict[int, list[dict]] = {}
    for row in rows:
        rows_by_product.setdefault(int(row["product_id"]), []).append(row)

    summary_client: AsyncClient | None = None
    if (
        (OPENROUTER_API_KEY and EPISODE_SUMMARY_MODEL)
        or (OPENROUTER_API_KEY and RP_OPENROUTER_MODEL)
        or (settings.ANTHROPIC_API_KEY and RP_REASONING_MODEL)
    ):
        summary_client = AsyncClient(timeout=EPISODE_SUMMARY_TIMEOUT_SECONDS)

    work_conn = db_connect()
    try:
        if args.apply:
            await assert_storyctx_apply_providers_ready(summary_client)
        for product_id, product_rows in rows_by_product.items():
            product_failed = False
            failed_ready_episode_count = 0
            with work_cursor(work_conn) as cur:
                total_episode_count = fetch_total_episode_count(cur=cur, product_id=product_id)
            episode_texts_by_no: dict[int, str] = {}

            with product_lock_connection(product_id) if args.apply else nullcontext(None) as lock_conn:
                if args.apply and lock_conn is None:
                    results["products"].append(
                        {
                            "product_id": product_id,
                            "context_status": "locked",
                            "total_episode_count": total_episode_count,
                            "ready_episode_count": 0,
                        }
                    )
                    if args.verbose:
                        print(f"[skip] product_id={product_id} lock busy")
                    continue

                try:
                    for row in product_rows:
                        source = await resolve_source_payload(row=row, use_epub_fallback=args.use_epub_fallback)
                        if source is None:
                            results["skipped_rows"] += 1
                            if args.verbose:
                                print(
                                    f"[skip] product_id={row['product_id']} episode_id={row['episode_id']} source unavailable"
                                )
                            continue

                        normalized_text = normalize_episode_html(source["html_content"])
                        if not normalized_text:
                            results["skipped_rows"] += 1
                            if args.verbose:
                                print(
                                    f"[skip] product_id={row['product_id']} episode_id={row['episode_id']} normalized text empty"
                                )
                            continue
                        episode_texts_by_no[int(row["episode_no"])] = normalized_text

                        chunks = build_chunks(normalized_text)
                        if not chunks:
                            results["skipped_rows"] += 1
                            if args.verbose:
                                print(
                                    f"[skip] product_id={row['product_id']} episode_id={row['episode_id']} chunks empty"
                                )
                            continue

                        source_hash = sha256_text(normalized_text)
                        with work_cursor(work_conn) as cur:
                            existing = fetch_existing_doc(
                                cur=cur,
                                episode_id=int(row["episode_id"]),
                                source_hash=source_hash,
                                source_type=str(source["source_type"]),
                            )

                        if args.apply:
                            try:
                                with work_cursor(work_conn) as cur:
                                    context_doc_id = insert_doc_and_chunks(
                                        cur=cur,
                                        row=row,
                                        source=source,
                                        normalized_text=normalized_text,
                                        chunks=chunks,
                                    )
                                work_conn.commit()
                                if existing:
                                    results["reused_docs"] += 1
                                else:
                                    results["inserted_docs"] += 1

                                _, inserted_summary, summary_meta = await insert_episode_summary(
                                    conn=work_conn,
                                    row=row,
                                    source_hash=source_hash,
                                    normalized_text=normalized_text,
                                    summary_client=summary_client,
                                    verbose=args.verbose,
                                )
                                if inserted_summary:
                                    results["inserted_summaries"] += 1
                                    if summary_meta.get("used_llm"):
                                        results["llm_generated_summaries"] += 1
                                        if int(summary_meta.get("retry_count") or 0) > 0:
                                            results["summary_retry_successes"] += 1
                                    elif summary_meta.get("fallback_used"):
                                        results["summary_fallbacks"] += 1
                                else:
                                    results["reused_summaries"] += 1
                                if args.verbose:
                                    print(
                                        f"[ok] product_id={row['product_id']} episode_no={row['episode_no']} "
                                        f"context_doc_id={context_doc_id} source={source['source_type']} chunks={len(chunks)} "
                                        f"summary_llm={summary_meta.get('used_llm')} "
                                        f"summary_fallback={summary_meta.get('fallback_used')}"
                                    )
                            except Exception as exc:
                                product_failed = True
                                failed_ready_episode_count = mark_product_context_failed(
                                    product_id=product_id,
                                    total_episode_count=total_episode_count,
                                    error_message=str(exc),
                                )
                                if args.verbose:
                                    print(
                                        f"[failed] product_id={product_id} episode_id={row['episode_id']} error={str(exc)[:200]}"
                                    )
                                break
                        else:
                            if existing:
                                results["reused_docs"] += 1
                            else:
                                results["inserted_docs"] += 1
                            with work_cursor(work_conn) as cur:
                                existing_summary = fetch_existing_summary(
                                    cur=cur,
                                    product_id=int(row["product_id"]),
                                    summary_type="episode_summary",
                                    scope_key=f"episode:{int(row['episode_id'])}",
                                    source_hash=build_summary_source_hash(source_hash, str(row.get("episode_title") or "")),
                                )
                            if existing_summary:
                                results["reused_summaries"] += 1
                            else:
                                results["inserted_summaries"] += 1
                            if args.verbose:
                                print(
                                    f"[dry-run] product_id={row['product_id']} episode_no={row['episode_no']} "
                                    f"source={source['source_type']} hash={source_hash[:10]} chunks={len(chunks)}"
                                )

                    if args.apply and not product_failed:
                        with work_cursor(work_conn) as cur:
                            compound_counts = build_compound_summaries(
                                cur=cur,
                                product_id=product_id,
                                product_title=str(product_rows[0].get("title") or ""),
                            )
                        work_conn.commit()
                        results["inserted_range_summaries"] += compound_counts["range"][0]
                        results["reused_range_summaries"] += compound_counts["range"][1]
                        results["inserted_product_summaries"] += compound_counts["product"][0]
                        results["reused_product_summaries"] += compound_counts["product"][1]
                        results["inserted_character_snapshots"] += compound_counts["character"][0]
                        results["reused_character_snapshots"] += compound_counts["character"][1]

                        with work_cursor(work_conn) as cur:
                            episode_summary_rows = fetch_active_summary_rows(cur=cur, product_id=product_id, summary_type="episode_summary")
                        episode_processing_rows, cleanup_episode_scopes = select_full_build_episode_rows(
                            product_rows=product_rows,
                            episode_summary_rows=episode_summary_rows,
                            args=args,
                        )
                        signal_counts = await build_episode_character_signals_summaries(
                            conn=work_conn,
                            product_id=product_id,
                            episode_rows=episode_processing_rows,
                            summary_client=summary_client,
                            verbose=args.verbose,
                            cleanup_missing_scopes=cleanup_episode_scopes,
                        )
                        results["inserted_episode_character_signals"] += signal_counts[0]
                        results["reused_episode_character_signals"] += signal_counts[1]

                        with work_cursor(work_conn) as cur:
                            inventory_signal_rows = fetch_active_summary_rows(
                                cur=cur,
                                product_id=product_id,
                                summary_type="episode_character_signals",
                            )
                        work_protagonist_resolution = await build_work_protagonist_resolution_for_inventory_v3(
                            product_id=product_id,
                            product_title=str(product_rows[0].get("title") or ""),
                            signal_rows=inventory_signal_rows,
                            summary_client=summary_client,
                            episode_summary_rows=episode_processing_rows,
                            verbose=args.verbose,
                        )

                        with work_cursor(work_conn) as cur:
                            inventory_counts = build_character_inventory_summaries(
                                cur=cur,
                                product_id=product_id,
                            )
                            inventory_v3_counts = build_character_inventory_v3_summaries(
                                cur=cur,
                                product_id=product_id,
                                protagonist_resolution=work_protagonist_resolution,
                            )
                            relation_counts = build_relation_inventory_summaries(
                                cur=cur,
                                product_id=product_id,
                            )
                            assert_story_agent_foundation_invariants(
                                cur=cur,
                                product_id=product_id,
                            )
                            inventory_v3_map = fetch_active_character_inventory_map(
                                cur=cur,
                                product_id=product_id,
                                summary_type="character_inventory_v3",
                            )
                            relation_map = fetch_active_relation_inventory_map(
                                cur=cur,
                                product_id=product_id,
                            )
                            relation_map = build_canonical_relation_inventory_map(
                                relation_map=relation_map,
                                inventory_map=inventory_v3_map,
                            )
                        work_conn.commit()
                        results["inserted_character_inventories"] += inventory_counts[0]
                        results["reused_character_inventories"] += inventory_counts[1]
                        results["inserted_character_inventory_v3"] += inventory_v3_counts[0]
                        results["reused_character_inventory_v3"] += inventory_v3_counts[1]
                        results["inserted_relation_inventories"] += relation_counts[0]
                        results["reused_relation_inventories"] += relation_counts[1]

                        scene_counts = await build_episode_scene_extraction_summaries_nonblocking(
                            conn=work_conn,
                            product_id=product_id,
                            product_title=str(product_rows[0].get("title") or ""),
                            episode_rows=episode_processing_rows,
                            episode_texts_by_no=episode_texts_by_no,
                            summary_client=summary_client,
                            canonical_character_packet=build_episode_scene_canonical_character_packet(inventory_v3_map),
                            verbose=args.verbose,
                            cleanup_missing_scopes=cleanup_episode_scopes,
                        )
                        results["inserted_episode_scene_extractions"] += scene_counts[0]
                        results["reused_episode_scene_extractions"] += scene_counts[1]

                        rp_counts = await build_rp_summaries(
                            conn=work_conn,
                            product_id=product_id,
                            episode_rows=episode_processing_rows,
                            episode_texts_by_no=episode_texts_by_no,
                            summary_client=summary_client,
                            inventory_map=inventory_v3_map,
                            relation_map=relation_map,
                            verbose=args.verbose,
                        )
                        results["inserted_character_rp_profiles"] += rp_counts["profile"][0]
                        results["reused_character_rp_profiles"] += rp_counts["profile"][1]
                        results["inserted_character_rp_examples"] += rp_counts["examples"][0]
                        results["reused_character_rp_examples"] += rp_counts["examples"][1]
                        with work_cursor(work_conn) as cur:
                            status_row = refresh_product_context_status(
                                cur=cur,
                                product_id=product_id,
                                total_episode_count=total_episode_count,
                            )
                            status_row = attach_character_chat_asset_readiness_to_status_row(
                                cur,
                                status_row,
                            )
                        work_conn.commit()
                        results["products"].append(status_row)
                    elif args.apply and product_failed:
                        results["products"].append(
                            {
                                "product_id": product_id,
                                "context_status": "failed",
                                "total_episode_count": total_episode_count,
                                "ready_episode_count": failed_ready_episode_count,
                            }
                        )
                    elif not args.apply:
                        results["products"].append(
                            {
                                "product_id": product_id,
                                "context_status": "dry-run",
                                "total_episode_count": total_episode_count,
                                "ready_episode_count": 0,
                            }
                        )
                except Exception as exc:
                    product_failed = True
                    if args.apply:
                        failed_ready_episode_count = mark_product_context_failed(
                            product_id=product_id,
                            total_episode_count=total_episode_count,
                            error_message=str(exc),
                        )
                        results["products"].append(
                            {
                                "product_id": product_id,
                                "context_status": "failed",
                                "total_episode_count": total_episode_count,
                                "ready_episode_count": failed_ready_episode_count,
                            }
                        )
                    else:
                        raise
                    if args.verbose:
                        print(f"[failed] product_id={product_id} error={str(exc)[:200]}")
    finally:
        if summary_client is not None:
            await summary_client.aclose()
        work_conn.close()
    return results


async def build_context_rows_delta(rows: Iterable[dict], args: argparse.Namespace) -> dict[str, object]:
    results = build_empty_results()

    rows_by_product: dict[int, list[dict]] = {}
    for row in rows:
        rows_by_product.setdefault(int(row["product_id"]), []).append(row)

    summary_client: AsyncClient | None = None
    if (
        (OPENROUTER_API_KEY and EPISODE_SUMMARY_MODEL)
        or (OPENROUTER_API_KEY and RP_OPENROUTER_MODEL)
        or (settings.ANTHROPIC_API_KEY and RP_REASONING_MODEL)
    ):
        summary_client = AsyncClient(timeout=EPISODE_SUMMARY_TIMEOUT_SECONDS)

    work_conn = db_connect()
    try:
        if args.apply:
            with work_cursor(work_conn) as cur:
                for product_id in sorted(rows_by_product):
                    touch_product_context_build_attempt(
                        cur,
                        product_id=product_id,
                    )
            work_conn.commit()
            await assert_storyctx_apply_providers_ready(summary_client)
        for product_id, product_rows in rows_by_product.items():
            product_failed = False
            failed_ready_episode_count = 0
            touched_episode_nos = sorted(
                set(int(row.get("episode_no") or 0) for row in product_rows if int(row.get("episode_no") or 0) > 0)
            )
            touched_range_scopes = select_touched_range_scopes(touched_episode_nos)
            with work_cursor(work_conn) as cur:
                total_episode_count = fetch_total_episode_count(cur=cur, product_id=product_id)

            with product_lock_connection(product_id) if args.apply else nullcontext(None) as lock_conn:
                if args.apply and lock_conn is None:
                    results["products"].append(
                        {
                            "product_id": product_id,
                            "context_status": "locked",
                            "total_episode_count": total_episode_count,
                            "ready_episode_count": 0,
                        }
                    )
                    continue

                try:
                    with work_cursor(work_conn) as cur:
                        old_inventory_map = fetch_active_character_inventory_map(cur=cur, product_id=product_id)
                        old_inventory_v3_map = fetch_active_character_inventory_map(
                            cur=cur,
                            product_id=product_id,
                            summary_type="character_inventory_v3",
                        )
                        old_relation_map = fetch_active_relation_inventory_by_relation_key_map(cur=cur, product_id=product_id)
                        old_profile_map = fetch_active_summary_state_map(
                            cur=cur,
                            product_id=product_id,
                            summary_type="character_rp_profile",
                        )
                        old_examples_map = fetch_active_summary_state_map(
                            cur=cur,
                            product_id=product_id,
                            summary_type="character_rp_examples",
                        )
                        old_internal_prompt_map = fetch_active_summary_state_map(
                            cur=cur,
                            product_id=product_id,
                            summary_type="character_chat_internal_prompt",
                        )
                        old_touched_signal_rows = fetch_active_summary_rows_for_episode_nos(
                            cur,
                            product_id=product_id,
                            summary_type="episode_character_signals",
                            episode_nos=touched_episode_nos,
                        )

                    for row in product_rows:
                        source = await resolve_source_payload(row=row, use_epub_fallback=args.use_epub_fallback)
                        if source is None:
                            results["skipped_rows"] += 1
                            continue

                        normalized_text = normalize_episode_html(source["html_content"])
                        if not normalized_text:
                            results["skipped_rows"] += 1
                            continue

                        chunks = build_chunks(normalized_text)
                        if not chunks:
                            results["skipped_rows"] += 1
                            continue

                        source_hash = sha256_text(normalized_text)
                        with work_cursor(work_conn) as cur:
                            existing = fetch_existing_doc(
                                cur=cur,
                                episode_id=int(row["episode_id"]),
                                source_hash=source_hash,
                                source_type=str(source["source_type"]),
                            )

                        if args.apply:
                            with work_cursor(work_conn) as cur:
                                insert_doc_and_chunks(
                                    cur=cur,
                                    row=row,
                                    source=source,
                                    normalized_text=normalized_text,
                                    chunks=chunks,
                                )
                            work_conn.commit()
                            if existing:
                                results["reused_docs"] += 1
                            else:
                                results["inserted_docs"] += 1

                            _, inserted_summary, summary_meta = await insert_episode_summary(
                                conn=work_conn,
                                row=row,
                                source_hash=source_hash,
                                normalized_text=normalized_text,
                                summary_client=summary_client,
                                verbose=args.verbose,
                            )
                            if inserted_summary:
                                results["inserted_summaries"] += 1
                                if summary_meta.get("used_llm"):
                                    results["llm_generated_summaries"] += 1
                                    if int(summary_meta.get("retry_count") or 0) > 0:
                                        results["summary_retry_successes"] += 1
                                elif summary_meta.get("fallback_used"):
                                    results["summary_fallbacks"] += 1
                            else:
                                results["reused_summaries"] += 1
                        else:
                            if existing:
                                results["reused_docs"] += 1
                            else:
                                results["inserted_docs"] += 1

                    if args.apply and not product_failed:
                        with work_cursor(work_conn) as cur:
                            touched_episode_summary_rows = fetch_active_summary_rows_for_episode_nos(
                                cur,
                                product_id=product_id,
                                summary_type="episode_summary",
                                episode_nos=touched_episode_nos,
                            )
                        signal_counts = await build_episode_character_signals_summaries(
                            conn=work_conn,
                            product_id=product_id,
                            episode_rows=touched_episode_summary_rows,
                            summary_client=summary_client,
                            cleanup_missing_scopes=False,
                            verbose=args.verbose,
                        )
                        results["inserted_episode_character_signals"] += signal_counts[0]
                        results["reused_episode_character_signals"] += signal_counts[1]

                        with work_cursor(work_conn) as cur:
                            active_signal_rows_for_resolution = fetch_active_summary_rows(
                                cur=cur,
                                product_id=product_id,
                                summary_type="episode_character_signals",
                            )
                            all_episode_summary_rows = fetch_active_summary_rows(
                                cur=cur,
                                product_id=product_id,
                                summary_type="episode_summary",
                            )
                        work_protagonist_resolution = await build_work_protagonist_resolution_for_inventory_v3(
                            product_id=product_id,
                            product_title=str(product_rows[0].get("title") or ""),
                            signal_rows=active_signal_rows_for_resolution,
                            summary_client=summary_client,
                            episode_summary_rows=all_episode_summary_rows,
                            verbose=args.verbose,
                        )

                        with work_cursor(work_conn) as cur:
                            compound_counts = build_compound_summaries_delta(
                                cur,
                                product_id=product_id,
                                product_title=str(product_rows[0].get("title") or ""),
                                touched_range_scopes=touched_range_scopes,
                            )
                            new_touched_signal_rows = fetch_active_summary_rows_for_episode_nos(
                                cur,
                                product_id=product_id,
                                summary_type="episode_character_signals",
                                episode_nos=touched_episode_nos,
                            )
                            inventory_counts = build_character_inventory_summaries_delta(
                                cur,
                                product_id=product_id,
                                old_inventory_map=old_inventory_map,
                                old_touched_signal_rows=old_touched_signal_rows,
                                new_touched_signal_rows=new_touched_signal_rows,
                            )
                            inventory_v3_counts = build_character_inventory_v3_summaries(
                                cur,
                                product_id=product_id,
                                protagonist_resolution=work_protagonist_resolution,
                            )
                            relation_counts = build_relation_inventory_summaries_delta(
                                cur,
                                product_id=product_id,
                                old_relation_map=old_relation_map,
                                old_touched_signal_rows=old_touched_signal_rows,
                                new_touched_signal_rows=new_touched_signal_rows,
                            )
                            character_cleanup = cleanup_duplicate_character_inventory_rows(
                                cur,
                                product_id=product_id,
                            )
                            cleanup_duplicate_relation_inventory_rows(
                                cur,
                                product_id=product_id,
                                canonical_character_key_by_display_name=dict(
                                    character_cleanup.get("canonical_character_key_by_display_name") or {}
                                ),
                            )
                            new_inventory_map = fetch_active_character_inventory_map(cur=cur, product_id=product_id)
                            new_inventory_v3_map = fetch_active_character_inventory_map(
                                cur=cur,
                                product_id=product_id,
                                summary_type="character_inventory_v3",
                            )
                            new_relation_map = fetch_active_relation_inventory_by_relation_key_map(cur=cur, product_id=product_id)
                            new_relation_scope_map = fetch_active_relation_inventory_map(cur=cur, product_id=product_id)
                            new_relation_scope_map = build_canonical_relation_inventory_map(
                                relation_map=new_relation_scope_map,
                                inventory_map=new_inventory_v3_map,
                            )
                            episode_texts_by_no = fetch_active_episode_texts_by_no(
                                cur,
                                product_id=product_id,
                            )
                        work_conn.commit()
                        scene_counts = await build_episode_scene_extraction_summaries_nonblocking(
                            conn=work_conn,
                            product_id=product_id,
                            product_title=str(product_rows[0].get("title") or ""),
                            episode_rows=touched_episode_summary_rows,
                            episode_texts_by_no=episode_texts_by_no,
                            summary_client=summary_client,
                            canonical_character_packet=build_episode_scene_canonical_character_packet(new_inventory_v3_map),
                            cleanup_missing_scopes=False,
                            verbose=args.verbose,
                        )
                        results["inserted_episode_scene_extractions"] += scene_counts[0]
                        results["reused_episode_scene_extractions"] += scene_counts[1]
                        with work_cursor(work_conn) as cur:
                            touched_scene_rows = fetch_active_summary_rows_for_episode_nos(
                                cur,
                                product_id=product_id,
                                summary_type="episode_scene_extraction",
                                episode_nos=touched_episode_nos,
                            )
                        scene_affected_scope_keys = set(
                            build_character_chat_scene_context_lines_by_scope(touched_scene_rows).keys()
                        )
                        rp_affected_scope_keys = compute_rp_affected_scope_keys(
                            old_inventory_map=old_inventory_v3_map,
                            new_inventory_map=new_inventory_v3_map,
                            old_relation_map=old_relation_map,
                            new_relation_map=new_relation_map,
                            old_touched_signal_rows=old_touched_signal_rows,
                            new_touched_signal_rows=new_touched_signal_rows,
                            old_profile_map=old_profile_map,
                            old_examples_map=old_examples_map,
                            old_internal_prompt_map=old_internal_prompt_map,
                            cleanup_scope_keys=set(character_cleanup.get("touched_scope_keys") or []),
                        )
                        rp_affected_scope_keys.update(scene_affected_scope_keys)
                        rp_counts = build_empty_delta_rp_counts()
                        opening_counts = (0, 0)
                        rp_scope_keys_to_build = select_delta_rp_scope_keys(
                            refresh_requested=should_refresh_delta_rp(args),
                            affected_scope_keys=rp_affected_scope_keys,
                            inventory_map=new_inventory_v3_map,
                            profile_map=old_profile_map,
                            examples_map=old_examples_map,
                        )
                        if rp_scope_keys_to_build:
                            if args.verbose and not should_refresh_delta_rp(args):
                                print(
                                    f"[delta-rp-missing-build] product_id={product_id} "
                                    f"scope_keys={','.join(sorted(rp_scope_keys_to_build))}"
                                )
                            with work_cursor(work_conn) as cur:
                                historical_inventory_state_map = (
                                    fetch_rp_ready_character_inventory_history_state_map(
                                        cur,
                                        product_id=product_id,
                                    )
                                )
                            rp_counts = await build_rp_summaries_delta(
                                conn=work_conn,
                                product_id=product_id,
                                affected_scope_keys=rp_scope_keys_to_build,
                                episode_rows=all_episode_summary_rows,
                                episode_texts_by_no=episode_texts_by_no,
                                summary_client=summary_client,
                                inventory_map=new_inventory_v3_map,
                                relation_map=new_relation_scope_map,
                                historical_inventory_state_map=historical_inventory_state_map,
                                verbose=args.verbose,
                            )
                        elif args.verbose and rp_affected_scope_keys:
                            print(
                                f"[delta-rp-skip] product_id={product_id} "
                                f"affected_scope_keys={len(rp_affected_scope_keys)}"
                            )
                        results["inserted_character_chat_openings"] += opening_counts[0]
                        results["reused_character_chat_openings"] += opening_counts[1]
                        with work_cursor(work_conn) as cur:
                            new_profile_map = fetch_active_summary_state_map(
                                cur=cur,
                                product_id=product_id,
                                summary_type="character_rp_profile",
                            )
                            new_examples_map = fetch_active_summary_state_map(
                                cur=cur,
                                product_id=product_id,
                                summary_type="character_rp_examples",
                            )
                            results["delta_verifications"].append(
                                build_delta_inventory_verification(
                                    product_id=product_id,
                                    old_inventory_map=old_inventory_map,
                                    new_inventory_map=new_inventory_map,
                                    old_relation_map=old_relation_map,
                                    new_relation_map=new_relation_map,
                                    old_touched_signal_rows=old_touched_signal_rows,
                                    new_touched_signal_rows=new_touched_signal_rows,
                                    character_delta_stats=inventory_counts,
                                    relation_delta_stats=relation_counts,
                                )
                            )
                            results["delta_verifications"][-1]["rp"] = build_rp_delta_verification(
                                product_id=product_id,
                                affected_scope_keys=rp_affected_scope_keys,
                                inventory_map=new_inventory_v3_map,
                                profile_map=new_profile_map,
                                examples_map=new_examples_map,
                                rp_counts=rp_counts,
                            )
                            assert_story_agent_foundation_invariants(
                                cur=cur,
                                product_id=product_id,
                            )
                            status_row = refresh_product_context_status(
                                cur=cur,
                                product_id=product_id,
                                total_episode_count=total_episode_count,
                            )
                            status_row = attach_character_chat_asset_readiness_to_status_row(
                                cur,
                                status_row,
                            )
                        work_conn.commit()
                        results["inserted_range_summaries"] += compound_counts["range"][0]
                        results["reused_range_summaries"] += compound_counts["range"][1]
                        results["inserted_product_summaries"] += compound_counts["product"][0]
                        results["reused_product_summaries"] += compound_counts["product"][1]
                        results["inserted_character_inventories"] += int(inventory_counts["inserted_count"])
                        results["reused_character_inventories"] += int(inventory_counts["reused_count"])
                        results["inserted_character_inventory_v3"] += inventory_v3_counts[0]
                        results["reused_character_inventory_v3"] += inventory_v3_counts[1]
                        results["inserted_relation_inventories"] += int(relation_counts["inserted_count"])
                        results["reused_relation_inventories"] += int(relation_counts["reused_count"])
                        results["inserted_character_rp_profiles"] += int((rp_counts.get("profile") or (0, 0))[0])
                        results["reused_character_rp_profiles"] += int((rp_counts.get("profile") or (0, 0))[1])
                        results["inserted_character_rp_examples"] += int((rp_counts.get("examples") or (0, 0))[0])
                        results["reused_character_rp_examples"] += int((rp_counts.get("examples") or (0, 0))[1])
                        results["products"].append(status_row)
                    elif args.apply and product_failed:
                        results["products"].append(
                            {
                                "product_id": product_id,
                                "context_status": "failed",
                                "total_episode_count": total_episode_count,
                                "ready_episode_count": failed_ready_episode_count,
                            }
                        )
                    else:
                        results["products"].append(
                            {
                                "product_id": product_id,
                                "context_status": "delta-dry-run",
                                "total_episode_count": total_episode_count,
                                "ready_episode_count": 0,
                            }
                        )
                except Exception as exc:
                    product_failed = True
                    if args.apply:
                        failed_ready_episode_count = mark_product_context_failed(
                            product_id=product_id,
                            total_episode_count=total_episode_count,
                            error_message=str(exc),
                        )
                        results["products"].append(
                            {
                                "product_id": product_id,
                                "context_status": "failed",
                                "total_episode_count": total_episode_count,
                                "ready_episode_count": failed_ready_episode_count,
                            }
                        )
                    else:
                        raise
                    if args.verbose:
                        print(f"[delta-failed] product_id={product_id} error={str(exc)[:200]}")
    finally:
        if summary_client is not None:
            await summary_client.aclose()
        work_conn.close()
    return results


def print_summary(results: dict[str, object], apply: bool) -> None:
    print(build_storyctx_provider_summary_line())
    print(
        f"mode={'apply' if apply else 'dry-run'} "
        f"product_ids={build_summary_product_ids(results)} "
        f"inserted_docs={results['inserted_docs']} reused_docs={results['reused_docs']} "
        f"inserted_summaries={results['inserted_summaries']} reused_summaries={results['reused_summaries']} "
        f"llm_generated_summaries={results['llm_generated_summaries']} "
        f"summary_retry_successes={results['summary_retry_successes']} "
        f"summary_fallbacks={results['summary_fallbacks']} "
        f"inserted_range_summaries={results['inserted_range_summaries']} reused_range_summaries={results['reused_range_summaries']} "
        f"inserted_product_summaries={results['inserted_product_summaries']} reused_product_summaries={results['reused_product_summaries']} "
        f"inserted_character_snapshots={results['inserted_character_snapshots']} reused_character_snapshots={results['reused_character_snapshots']} "
        f"inserted_episode_character_signals={results['inserted_episode_character_signals']} reused_episode_character_signals={results['reused_episode_character_signals']} "
        f"inserted_episode_scene_extractions={results['inserted_episode_scene_extractions']} reused_episode_scene_extractions={results['reused_episode_scene_extractions']} "
        f"inserted_character_inventories={results['inserted_character_inventories']} reused_character_inventories={results['reused_character_inventories']} "
        f"inserted_character_inventory_v3={results['inserted_character_inventory_v3']} reused_character_inventory_v3={results['reused_character_inventory_v3']} "
        f"inserted_relation_inventories={results['inserted_relation_inventories']} reused_relation_inventories={results['reused_relation_inventories']} "
        f"inserted_character_rp_profiles={results['inserted_character_rp_profiles']} reused_character_rp_profiles={results['reused_character_rp_profiles']} "
        f"inserted_character_rp_examples={results['inserted_character_rp_examples']} reused_character_rp_examples={results['reused_character_rp_examples']} "
        f"inserted_character_chat_openings={results['inserted_character_chat_openings']} reused_character_chat_openings={results['reused_character_chat_openings']} "
        f"character_asset_repair_attempted={results['character_asset_repair_attempted']} "
        f"character_asset_repair_recovered={results['character_asset_repair_recovered']} "
        f"character_asset_repair_no_progress={results['character_asset_repair_no_progress']} "
        f"character_asset_repair_failed={results['character_asset_repair_failed']} "
        f"skipped_rows={results['skipped_rows']}"
    )
    for product in list(results.get("products") or [])[:20]:
        print(
            "product",
            f"product_id={product['product_id']}",
            f"status={product['context_status']}",
            f"ready={product['ready_episode_count']}",
            f"total={product['total_episode_count']}",
        )
    delta_verifications = list(results.get("delta_verifications") or [])
    if delta_verifications:
        print(
            "delta-verify-summary",
            f"products={len(list(results.get('products') or []))}",
            f"items={len(delta_verifications)}",
            f"touched_characters={sum(int(item.get('touched_character_keys') or 0) for item in delta_verifications)}",
            f"new_characters={sum(int(item.get('new_character_keys') or 0) for item in delta_verifications)}",
            f"character_keep_old={sum(int(item.get('character_keep_old_missing') or 0) for item in delta_verifications)}",
            f"character_skip_new={sum(int(item.get('character_skip_new') or 0) for item in delta_verifications)}",
            f"touched_relations={sum(int(item.get('touched_relation_keys') or 0) for item in delta_verifications)}",
            f"new_relations={sum(int(item.get('new_relation_keys') or 0) for item in delta_verifications)}",
            f"relation_keep_old={sum(int(item.get('relation_keep_old_missing') or 0) for item in delta_verifications)}",
            f"relation_skip_new={sum(int(item.get('relation_skip_new') or 0) for item in delta_verifications)}",
            f"products_with_protagonist_change={sum(1 for item in delta_verifications if bool(item.get('protagonist_changed')))}",
            f"duplicate_character_name_groups={sum(len(item.get('duplicate_character_names') or {}) for item in delta_verifications)}",
            f"duplicate_relation_edge_groups={sum(len(item.get('duplicate_relation_edges') or {}) for item in delta_verifications)}",
        )
    for verification in delta_verifications[:20]:
        duplicate_character_names = verification.get("duplicate_character_names") or {}
        duplicate_relation_edges = verification.get("duplicate_relation_edges") or {}
        print(
            "delta-verify",
            f"product_id={verification['product_id']}",
            f"touched_characters={verification['touched_character_keys']}",
            f"new_characters={verification['new_character_keys']}",
            f"character_keep_old={verification['character_keep_old_missing']}",
            f"character_skip_new={verification['character_skip_new']}",
            f"touched_relations={verification['touched_relation_keys']}",
            f"new_relations={verification['new_relation_keys']}",
            f"relation_keep_old={verification['relation_keep_old_missing']}",
            f"relation_skip_new={verification['relation_skip_new']}",
            f"protagonist_changed={int(bool(verification.get('protagonist_changed')))}",
            f"duplicate_character_names={len(duplicate_character_names)}",
            f"duplicate_relation_edges={len(duplicate_relation_edges)}",
        )
        if duplicate_character_names:
            print(
                "delta-verify-detail",
                f"product_id={verification['product_id']}",
                "duplicate_character_names=" + json.dumps(duplicate_character_names, ensure_ascii=False),
            )
        if duplicate_relation_edges:
            print(
                "delta-verify-detail",
                f"product_id={verification['product_id']}",
                "duplicate_relation_edges=" + json.dumps(duplicate_relation_edges, ensure_ascii=False),
            )


def write_delta_verification_json(path_str: str, results: dict[str, object]) -> None:
    target = str(path_str or "").strip()
    if not target:
        return
    delta_verifications = list(results.get("delta_verifications") or [])
    summary = {
        "product_count": len(list(results.get("products") or [])),
        "verification_count": len(delta_verifications),
        "touched_character_keys": sum(int(item.get("touched_character_keys") or 0) for item in delta_verifications),
        "new_character_keys": sum(int(item.get("new_character_keys") or 0) for item in delta_verifications),
        "character_keep_old_missing": sum(int(item.get("character_keep_old_missing") or 0) for item in delta_verifications),
        "character_skip_new": sum(int(item.get("character_skip_new") or 0) for item in delta_verifications),
        "touched_relation_keys": sum(int(item.get("touched_relation_keys") or 0) for item in delta_verifications),
        "new_relation_keys": sum(int(item.get("new_relation_keys") or 0) for item in delta_verifications),
        "relation_keep_old_missing": sum(int(item.get("relation_keep_old_missing") or 0) for item in delta_verifications),
        "relation_skip_new": sum(int(item.get("relation_skip_new") or 0) for item in delta_verifications),
        "products_with_protagonist_change": sum(1 for item in delta_verifications if bool(item.get("protagonist_changed"))),
        "duplicate_character_name_groups": sum(len(item.get("duplicate_character_names") or {}) for item in delta_verifications),
        "duplicate_relation_edge_groups": sum(len(item.get("duplicate_relation_edges") or {}) for item in delta_verifications),
    }
    payload = {
        "products": list(results.get("products") or []),
        "summary": summary,
        "delta_verifications": delta_verifications,
    }
    try:
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(
            "delta-verify-json",
            f"path={path}",
            f"items={len(payload['delta_verifications'])}",
        )
    except Exception as exc:
        print(
            f"[delta-verify-json-failed] path={target} error={str(exc)[:200]}",
            file=sys.stderr,
        )


async def main() -> int:
    args = parse_args()
    validate_delta_args(args)
    query, params = build_target_query(args=args, use_epub_fallback=args.use_epub_fallback)
    rows: list[dict] = []
    character_asset_repair_rows: list[dict] = []
    delta_status_repaired_products: list[dict[str, object]] = []
    conn = db_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = list(cur.fetchall())
            if args.build_mode == "delta":
                if args.apply and bool(args.repair_character_assets):
                    character_asset_repair_rows = list(rows)
                if args.apply:
                    delta_status_repaired_products = repair_failed_delta_context_statuses(cur, rows)
                    if delta_status_repaired_products:
                        conn.commit()
                rows = filter_delta_candidate_rows(
                    cur,
                    rows,
                    max_delta_episodes=args.max_delta_episodes,
                )
            if args.build_mode == "delta" and not args.apply:
                plans = build_delta_scope_plans(cur, rows)
                print_delta_scope_plans(plans)
                return 0
    finally:
        conn.close()

    if args.build_mode == "delta":
        results = (
            await build_context_rows_delta(rows=rows, args=args)
            if rows
            else build_empty_results()
        )
        if delta_status_repaired_products:
            results["products"] = [
                *delta_status_repaired_products,
                *list(results.get("products") or []),
            ]
        if character_asset_repair_rows:
            await repair_character_chat_assets(
                rows=character_asset_repair_rows,
                args=args,
                results=results,
            )
        print_summary(results=results, apply=args.apply)
        write_delta_verification_json(args.verification_json_path, results)
        return build_delta_exit_code(results, apply=args.apply)

    results = await build_context_rows(rows=rows, args=args)
    print_summary(results=results, apply=args.apply)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
