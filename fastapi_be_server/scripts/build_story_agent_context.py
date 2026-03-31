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
import os
import re
import sys
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

DB_HOST = os.getenv("BATCH_DB_HOST", settings.DB_IP)
DB_PORT = int(os.getenv("BATCH_DB_PORT", str(settings.DB_PORT)))
DB_USER = os.getenv("BATCH_DB_USER", settings.DB_USER_ID)
DB_PASSWORD = os.getenv("BATCH_DB_PASSWORD", settings.DB_USER_PW)
DB_NAME = os.getenv("BATCH_DB_NAME", "likenovel")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
EPISODE_SUMMARY_MODEL = os.getenv("STORY_AGENT_SUMMARY_MODEL", "deepseek/deepseek-v3.2").strip()
RP_REASONING_MODEL = (os.getenv("STORY_AGENT_RP_REASONING_MODEL", "").strip() or "claude-sonnet-4-6")
if RP_REASONING_MODEL.startswith("anthropic."):
    RP_REASONING_MODEL = RP_REASONING_MODEL.split(".", 1)[1].strip()
RP_REASONING_EFFORT = (os.getenv("STORY_AGENT_RP_REASONING_EFFORT", "medium").strip() or "medium")
RP_REASONING_THINKING_DISPLAY = (os.getenv("STORY_AGENT_RP_REASONING_THINKING_DISPLAY", "omitted").strip() or "omitted")
EPISODE_SUMMARY_TIMEOUT_SECONDS = 120.0
EPISODE_SUMMARY_TEMPERATURE = float(os.getenv("STORY_AGENT_SUMMARY_TEMPERATURE", "0.0"))
EPISODE_SUMMARY_MAX_OUTPUT_TOKENS = 1400
EPISODE_SUMMARY_MAX_INPUT_CHARS = 10000

TARGET_CHUNK_LEN = 1600
MAX_CHUNK_LEN = 2500
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+|(?<=다\.)\s+|(?<=요\.)\s+")
KEYWORD_RE = re.compile(r"[가-힣A-Za-z0-9]{2,}")
EPISODE_SUMMARY_FORMAT_VERSION = "episode_summary_v11"
RANGE_SUMMARY_FORMAT_VERSION = "range_summary_v1"
PRODUCT_SUMMARY_FORMAT_VERSION = "product_summary_v1"
CHARACTER_SNAPSHOT_FORMAT_VERSION = "character_snapshot_v1"
CHARACTER_RP_PROFILE_FORMAT_VERSION = "character_rp_profile_v3"
CHARACTER_RP_EXAMPLES_FORMAT_VERSION = "character_rp_examples_v3"
DIALOGUE_QUOTE_RE = re.compile(r'["“](.*?)["”]', re.S)
FIRST_PERSON_MONOLOGUE_RE = re.compile(r"\b(나는|내가|난|나를|내게|내겐|내 마음|내 생각|내 판단)\b")
RP_SIMPLE_VOCATIVE_RE = re.compile(r"^[가-힣A-Za-z0-9]{2,12}(?:아|야)?[!?.…~]*$")
RP_NOISE_ONLY_RE = re.compile(r"^[!?.…~ㅋㅎㅠㅜ\s]+$")
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
"""

RP_DIALOGUE_COLLECTION_PROMPT = """너는 웹소설 원문에서 특정 캐릭터의 대사만 수집하는 전처리기다.
반드시 JSON만 반환하라. 원문에 없는 정보는 만들지 마라.

일반 캐릭터면 직접 말한 대사만 dialogue로 뽑아라.
1인칭 서술 작품의 주인공이면 아래 두 종류를 구분하라.
- dialogue: 직접 말한 대사
- monologue: 1인칭 감정/판단이 드러나는 내면 서술

출력 스키마:
{"items":[{"kind":"dialogue|monologue","context":"상황 5자 이내","text":"원문 그대로"}]}
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="스토리 에이전트 원문 컨텍스트 적재")
    parser.add_argument("--product-id", type=int, action="append", dest="product_ids", help="대상 작품 ID. 여러 번 지정 가능")
    parser.add_argument("--episode-id", type=int, action="append", dest="episode_ids", help="대상 회차 ID. 여러 번 지정 가능")
    parser.add_argument("--limit", type=int, default=0, help="대상 제한 건수")
    parser.add_argument("--apply", action="store_true", help="실제 DB 적재 수행")
    parser.add_argument("--verbose", action="store_true", help="상세 로그 출력")
    parser.add_argument("--use-epub-fallback", action="store_true", help="episode_content가 비어 있으면 EPUB에서 임시 원문 추출")
    return parser.parse_args()


def db_connect():
    if not DB_USER or not DB_PASSWORD:
        raise RuntimeError("DB 접속 정보가 비어 있습니다. BATCH_DB_* 또는 app.const.settings를 확인하세요.")
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
        autocommit=False,
        client_flag=CLIENT.MULTI_STATEMENTS,
        cursorclass=DictCursor,
    )


def acquire_product_lock(cur, product_id: int) -> bool:
    cur.execute("SELECT GET_LOCK(%s, 0) AS locked", (f"story-agent-context-product:{product_id}",))
    row = cur.fetchone() or {}
    return int(row.get("locked") or 0) == 1


def release_product_lock(cur, product_id: int) -> None:
    cur.execute("SELECT RELEASE_LOCK(%s)", (f"story-agent-context-product:{product_id}",))


def build_target_query(args: argparse.Namespace, use_epub_fallback: bool) -> tuple[str, list[object]]:
    where = [
        "p.price_type = 'free'",
        "pe.use_yn = 'Y'",
        "pe.open_yn = 'Y'",
        "p.open_yn = 'Y'",
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
        f"원문:\n{normalized_text[:EPISODE_SUMMARY_MAX_INPUT_CHARS]}"
    )


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
        last_candidate = repaired_text
        last_issues = issues
        if valid:
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

        if not is_critical and repaired_text:
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
    return "|".join(
        [
            RP_REASONING_MODEL,
            RP_REASONING_EFFORT,
            RP_REASONING_THINKING_DISPLAY,
        ]
    )


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
        is_protagonist = bool(item.get("is_protagonist"))
        is_first_person = bool(item.get("is_first_person")) if is_protagonist else False
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


def build_rp_dialogue_collection_user_prompt(target: dict[str, object], normalized_text: str) -> str:
    if bool(target.get("is_protagonist")) and bool(target.get("is_first_person")):
        role_line = "1인칭 서술 작품의 주인공이다."
    else:
        role_line = f"대상 캐릭터명: {str(target.get('reference_name') or '').strip()}"
    return (
        f"{role_line}\n"
        "아래 원문에서 조건에 맞는 항목만 JSON으로 뽑아라.\n\n"
        f"원문:\n{normalized_text[:EPISODE_SUMMARY_MAX_INPUT_CHARS]}"
    )


def build_rp_profile_synthesis_user_prompt(
    target: dict[str, object],
    dialogue_items: list[dict[str, object]],
    summary_context_lines: list[str],
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
    return (
        f"캐릭터명: {str(target.get('display_name') or '').strip()}\n"
        f"aliases: {', '.join(str(alias).strip() for alias in (target.get('aliases') or []) if str(alias).strip())}\n\n"
        f"is_protagonist: {'Y' if bool(target.get('is_protagonist')) else 'N'}\n"
        f"is_first_person: {'Y' if bool(target.get('is_first_person')) else 'N'}\n\n"
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


def split_text_lines(normalized_text: str) -> list[str]:
    return [re.sub(r"[ \t]+", " ", line).strip() for line in str(normalized_text or "").splitlines() if line.strip()]


def normalize_rp_text(value: str, *, limit: int = 300) -> str:
    cleaned = re.sub(r"\s+", " ", str(value or "").replace("\u3000", " ")).strip()
    return cleaned[:limit]


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
            items.append(
                {
                    "kind": "dialogue",
                    "context": build_rp_context(line, prev_line),
                    "text": text_value,
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


def collect_rule_based_rp_dialogue_items(target: dict[str, object], normalized_text: str) -> list[dict[str, object]]:
    collection_rules = target.get("collection_rules") or {}
    use_dialogue = bool(collection_rules.get("use_dialogue", True))
    use_monologue = bool(collection_rules.get("use_monologue", False))
    speaker_anchors = [str(anchor).strip() for anchor in (collection_rules.get("speaker_anchors") or target.get("aliases") or []) if str(anchor).strip()]
    exclude_tokens = [str(token).strip() for token in (collection_rules.get("exclude_tokens") or []) if str(token).strip()]

    dialogue_segments = extract_dialogue_segments(normalized_text)
    if bool(target.get("is_protagonist")) and bool(target.get("is_first_person")):
        collected: list[dict[str, object]] = []
        if use_dialogue:
            collected.extend(dialogue_segments)
        if use_monologue:
            collected.extend(extract_first_person_monologues(normalized_text))
        return collected

    if not use_dialogue or not speaker_anchors:
        return []

    matched: list[dict[str, object]] = []
    for item in dialogue_segments:
        hint = str(item.get("speaker_hint") or "")
        if exclude_tokens and any(token in hint for token in exclude_tokens):
            continue
        if any(alias in hint for alias in speaker_anchors):
            matched.append(item)
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
        json={
            "model": EPISODE_SUMMARY_MODEL,
            "temperature": 0.0,
            "max_completion_tokens": 900,
            "messages": [
                {"role": "system", "content": RP_DIALOGUE_COLLECTION_PROMPT},
                {"role": "user", "content": build_rp_dialogue_collection_user_prompt(target, normalized_text)},
            ],
        },
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
        cleaned.append(
            {
                "kind": str(item.get("kind") or "dialogue").strip().lower() or "dialogue",
                "context": str(item.get("context") or "").strip()[:20],
                "text": text_value[:300],
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

    if settings.ANTHROPIC_API_KEY and RP_REASONING_MODEL:
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
                    "max_tokens": 2400,
                    "system": RP_CHARACTER_PLAN_PROMPT,
                    "messages": [{"role": "user", "content": user_prompt}],
                    **build_anthropic_reasoning_options(RP_REASONING_MODEL),
                },
            )
            response.raise_for_status()
            parsed = extract_json_object(extract_anthropic_message_text(response.json()))
            if parsed:
                return parsed
        except (HTTPStatusError, RequestError, ValueError):
            pass

    response = await client.post(
        f"{OPENROUTER_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "X-Title": "LikeNovel Story Agent RP Character Plan Batch",
        },
        json={
            "model": EPISODE_SUMMARY_MODEL,
            "temperature": 0.0,
            "max_completion_tokens": 1400,
            "messages": [
                {"role": "system", "content": RP_CHARACTER_PLAN_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        },
    )
    response.raise_for_status()
    return extract_json_object(extract_openrouter_message_text(response.json()))


async def request_rp_profile_payload(
    client: AsyncClient,
    *,
    target: dict[str, object],
    dialogue_items: list[dict[str, object]],
    summary_context_lines: list[str],
) -> dict | None:
    user_prompt = build_rp_profile_synthesis_user_prompt(
        target,
        dialogue_items,
        summary_context_lines,
    )

    if settings.ANTHROPIC_API_KEY and RP_REASONING_MODEL:
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
                    "max_tokens": 1800,
                    "system": RP_PROFILE_SYNTHESIS_PROMPT,
                    "messages": [{"role": "user", "content": user_prompt}],
                    **build_anthropic_reasoning_options(RP_REASONING_MODEL),
                },
            )
            response.raise_for_status()
            parsed = extract_json_object(extract_anthropic_message_text(response.json()))
            if parsed:
                return parsed
        except (HTTPStatusError, RequestError, ValueError):
            pass

    response = await client.post(
        f"{OPENROUTER_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "X-Title": "LikeNovel Story Agent RP Profile Batch",
        },
        json={
            "model": EPISODE_SUMMARY_MODEL,
            "temperature": 0.0,
            "max_completion_tokens": 1000,
            "messages": [
                {"role": "system", "content": RP_PROFILE_SYNTHESIS_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        },
    )
    response.raise_for_status()
    return extract_json_object(extract_openrouter_message_text(response.json()))


async def build_rp_summaries(
    cur,
    *,
    product_id: int,
    episode_rows: list[dict],
    episode_texts_by_no: dict[int, str],
    summary_client: AsyncClient | None,
    verbose: bool = False,
) -> dict[str, tuple[int, int]]:
    counts = {
        "profile": [0, 0],
        "examples": [0, 0],
    }
    if summary_client is None or not OPENROUTER_API_KEY or not EPISODE_SUMMARY_MODEL:
        return {key: (value[0], value[1]) for key, value in counts.items()}

    targets: list[dict[str, object]] = []
    try:
        plan_payload = await request_rp_character_plan_payload(
            summary_client,
            episode_rows=episode_rows,
            episode_texts_by_no=episode_texts_by_no,
        )
        targets = normalize_rp_character_plan(plan_payload, episode_rows, episode_texts_by_no)
    except Exception as exc:
        if verbose:
            print(f"[rp-plan-fallback] product_id={product_id} error={str(exc)[:160]}")
    if not targets:
        targets = build_rp_character_targets(episode_rows, episode_texts_by_no)

    valid_scope_keys: set[str] = set()
    for target in targets:
        character_key = str(target.get("character_key") or "").strip()
        if not character_key:
            continue
        aliases = [str(alias).strip() for alias in (target.get("aliases") or []) if str(alias).strip()]
        dialogue_items: list[dict[str, object]] = []
        priority_episode_nos = [int(no) for no in (target.get("evidence_episodes") or []) if int(no) in episode_texts_by_no]
        remaining_episode_nos = [
            int(no)
            for no in sorted(episode_texts_by_no.keys())
            if int(no) not in set(priority_episode_nos)
        ]
        ordered_episode_nos = priority_episode_nos + remaining_episode_nos
        for episode_no in ordered_episode_nos:
            normalized_text = str(episode_texts_by_no.get(episode_no) or "")
            if not normalized_text:
                continue
            extracted_items = collect_rule_based_rp_dialogue_items(target, normalized_text)
            for item in extracted_items:
                item["episode_no"] = episode_no
                dialogue_items.append(item)

        dialogue_items = dedupe_rp_dialogue_items(dialogue_items, limit=80)
        dialogue_items = mark_rp_example_candidates(dialogue_items, aliases)
        summary_context_lines = collect_rp_summary_context_lines(target, episode_rows)

        if not dialogue_items:
            continue

        try:
            payload = await request_rp_profile_payload(
                summary_client,
                target=target,
                dialogue_items=dialogue_items,
                summary_context_lines=summary_context_lines,
            )
        except Exception as exc:
            if verbose:
                print(f"[rp-profile-skip] product_id={product_id} character={character_key} error={str(exc)[:160]}")
            continue
        if not payload:
            continue

        profile_payload = {
            "character_key": character_key,
            "display_name": str(target.get("display_name") or "").strip() or str(target.get("reference_name") or "").strip(),
            "aliases": [str(alias).strip() for alias in (target.get("aliases") or []) if str(alias).strip()],
            "speech_style": payload.get("speech_style") or {},
            "personality_core": [str(item).strip() for item in (payload.get("personality_core") or []) if str(item).strip()][:2],
            "baseline_attitude": str(payload.get("baseline_attitude") or "").strip() or "무난",
        }
        example_texts = [
            str(item).strip()
            for item in (payload.get("example_dialogues") or [])
            if str(item).strip() and is_preferred_rp_example_text(str(item).strip(), aliases)
        ][:5]
        if not example_texts:
            fallback_candidates = sorted(
                [
                    item for item in dialogue_items
                    if bool(item.get("is_example_candidate")) and str(item.get("text") or "").strip()
                ],
                key=lambda item: (
                    -int(item.get("example_score") or 0),
                    int(item.get("episode_no") or 0),
                ),
            )
            example_texts = [
                str(item.get("text") or "").strip()
                for item in fallback_candidates
            ][:5]
        if not example_texts:
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

        profile_source_hash = build_compound_summary_source_hash(
            CHARACTER_RP_PROFILE_FORMAT_VERSION,
            [
                character_key,
                build_rp_reasoning_signature(),
                *(f"{int(item.get('episode_no') or 0)}:{str(item.get('text') or '')}" for item in dialogue_items[:40]),
            ],
        )
        examples_source_hash = build_compound_summary_source_hash(
            CHARACTER_RP_EXAMPLES_FORMAT_VERSION,
            [
                character_key,
                build_rp_reasoning_signature(),
                *(str(item.get("text") or "") for item in example_payload["examples"]),
            ],
        )
        valid_scope_keys.add(character_key)
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
        counts["profile"][0 if profile_inserted else 1] += 1
        counts["examples"][0 if examples_inserted else 1] += 1

    deactivate_missing_active_scopes(cur, product_id, "character_rp_profile", valid_scope_keys)
    deactivate_missing_active_scopes(cur, product_id, "character_rp_examples", valid_scope_keys)
    return {key: (value[0], value[1]) for key, value in counts.items()}


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
) -> tuple[int, bool]:
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
        SELECT summary_id, version_no, is_active
          FROM tb_story_agent_context_summary
         WHERE product_id = %s
           AND summary_type = %s
           AND scope_key = %s
           AND source_hash = %s
         LIMIT 1
        """,
        (product_id, summary_type, scope_key, source_hash),
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
    cur,
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

    existing = fetch_existing_summary(
        cur=cur,
        product_id=product_id,
        summary_type=summary_type,
        scope_key=scope_key,
        source_hash=summary_source_hash,
    )
    if existing:
        activate_existing_summary(cur, int(existing["summary_id"]), product_id, summary_type, scope_key)
        return int(existing["summary_id"]), False, {
            "used_llm": False,
            "retry_count": 0,
            "fallback_used": False,
            "fallback_reason": "",
        }

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
    summary_text, summary_meta = await generate_episode_summary_text(
        client=summary_client,
        row=row,
        normalized_text=normalized_text,
        verbose=verbose,
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
        ) VALUES (%s, %s, %s, %s, %s, %s, 1, %s, 'Y', %s, %s)
        """,
        (
            product_id,
            summary_type,
            scope_key,
            episode_no,
            episode_no,
            summary_source_hash,
            version_no,
            summary_text,
            settings.DB_DML_DEFAULT_ID,
        ),
    )
    return int(cur.lastrowid), True, summary_meta


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
            context_status = VALUES(context_status),
            total_episode_count = VALUES(total_episode_count),
            ready_episode_count = VALUES(ready_episode_count),
            last_built_at = VALUES(last_built_at),
            last_error_message = NULL,
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


def fetch_total_episode_count(cur, product_id: int) -> int:
    cur.execute(
        """
        SELECT COUNT(*) AS total_episode_count
          FROM tb_product p
          JOIN tb_product_episode pe
            ON pe.product_id = p.product_id
         WHERE p.product_id = %s
           AND p.price_type = 'free'
           AND pe.use_yn = 'Y'
           AND pe.open_yn = 'Y'
        """,
        (product_id,),
    )
    row = cur.fetchone() or {}
    return int(row.get("total_episode_count") or 0)


async def build_context_rows(rows: Iterable[dict], args: argparse.Namespace, conn) -> dict[str, object]:
    results = {
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
        "inserted_character_rp_profiles": 0,
        "reused_character_rp_profiles": 0,
        "inserted_character_rp_examples": 0,
        "reused_character_rp_examples": 0,
        "skipped_rows": 0,
        "products": [],
    }

    rows_by_product: dict[int, list[dict]] = {}
    for row in rows:
        rows_by_product.setdefault(int(row["product_id"]), []).append(row)

    summary_client: AsyncClient | None = None
    if OPENROUTER_API_KEY and EPISODE_SUMMARY_MODEL:
        summary_client = AsyncClient(timeout=EPISODE_SUMMARY_TIMEOUT_SECONDS)

    try:
        with conn.cursor() as cur:
            for product_id, product_rows in rows_by_product.items():
                product_failed = False
                failed_ready_episode_count = 0
                total_episode_count = fetch_total_episode_count(cur=cur, product_id=product_id)
                episode_texts_by_no: dict[int, str] = {}
                product_lock_acquired = False
                if args.apply:
                    product_lock_acquired = acquire_product_lock(cur, product_id)
                    if not product_lock_acquired:
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
                    cur.execute("SAVEPOINT story_agent_product_batch")
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
                        existing = fetch_existing_doc(
                            cur=cur,
                            episode_id=int(row["episode_id"]),
                            source_hash=source_hash,
                            source_type=str(source["source_type"]),
                        )

                        if args.apply:
                            try:
                                context_doc_id = insert_doc_and_chunks(
                                    cur=cur,
                                    row=row,
                                    source=source,
                                    normalized_text=normalized_text,
                                    chunks=chunks,
                                )
                                if existing:
                                    results["reused_docs"] += 1
                                else:
                                    results["inserted_docs"] += 1
                                _, inserted_summary, summary_meta = await insert_episode_summary(
                                    cur=cur,
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
                                cur.execute("ROLLBACK TO SAVEPOINT story_agent_product_batch")
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
                                failed_ready_episode_count = int(ready_row.get("ready_episode_count") or 0)
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
                                        context_status = 'failed',
                                        total_episode_count = VALUES(total_episode_count),
                                        ready_episode_count = VALUES(ready_episode_count),
                                        last_error_message = VALUES(last_error_message),
                                        updated_id = VALUES(updated_id)
                                    """,
                                    (
                                        product_id,
                                        total_episode_count,
                                        failed_ready_episode_count,
                                        str(exc)[:500],
                                        settings.DB_DML_DEFAULT_ID,
                                        settings.DB_DML_DEFAULT_ID,
                                    ),
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
                        compound_counts = build_compound_summaries(
                            cur=cur,
                            product_id=product_id,
                            product_title=str(product_rows[0].get("title") or ""),
                        )
                        results["inserted_range_summaries"] += compound_counts["range"][0]
                        results["reused_range_summaries"] += compound_counts["range"][1]
                        results["inserted_product_summaries"] += compound_counts["product"][0]
                        results["reused_product_summaries"] += compound_counts["product"][1]
                        results["inserted_character_snapshots"] += compound_counts["character"][0]
                        results["reused_character_snapshots"] += compound_counts["character"][1]
                        rp_counts = await build_rp_summaries(
                            cur=cur,
                            product_id=product_id,
                            episode_rows=fetch_active_summary_rows(cur=cur, product_id=product_id, summary_type="episode_summary"),
                            episode_texts_by_no=episode_texts_by_no,
                            summary_client=summary_client,
                            verbose=args.verbose,
                        )
                        results["inserted_character_rp_profiles"] += rp_counts["profile"][0]
                        results["reused_character_rp_profiles"] += rp_counts["profile"][1]
                        results["inserted_character_rp_examples"] += rp_counts["examples"][0]
                        results["reused_character_rp_examples"] += rp_counts["examples"][1]

                        status_row = refresh_product_context_status(
                            cur=cur,
                            product_id=product_id,
                            total_episode_count=total_episode_count,
                        )
                        results["products"].append(status_row)
                        cur.execute("RELEASE SAVEPOINT story_agent_product_batch")
                        conn.commit()
                    elif args.apply and product_failed:
                        results["products"].append(
                            {
                                "product_id": product_id,
                                "context_status": "failed",
                                "total_episode_count": total_episode_count,
                                "ready_episode_count": failed_ready_episode_count,
                            }
                        )
                        cur.execute("RELEASE SAVEPOINT story_agent_product_batch")
                        conn.commit()
                    elif not args.apply:
                        results["products"].append(
                            {
                                "product_id": product_id,
                                "context_status": "dry-run",
                                "total_episode_count": total_episode_count,
                                "ready_episode_count": 0,
                            }
                        )
                finally:
                    if args.apply and product_lock_acquired:
                        release_product_lock(cur, product_id)
    finally:
        if summary_client is not None:
            await summary_client.aclose()
    return results


def print_summary(results: dict[str, object], apply: bool) -> None:
    print(
        f"mode={'apply' if apply else 'dry-run'} "
        f"inserted_docs={results['inserted_docs']} reused_docs={results['reused_docs']} "
        f"inserted_summaries={results['inserted_summaries']} reused_summaries={results['reused_summaries']} "
        f"llm_generated_summaries={results['llm_generated_summaries']} "
        f"summary_retry_successes={results['summary_retry_successes']} "
        f"summary_fallbacks={results['summary_fallbacks']} "
        f"inserted_range_summaries={results['inserted_range_summaries']} reused_range_summaries={results['reused_range_summaries']} "
        f"inserted_product_summaries={results['inserted_product_summaries']} reused_product_summaries={results['reused_product_summaries']} "
        f"inserted_character_snapshots={results['inserted_character_snapshots']} reused_character_snapshots={results['reused_character_snapshots']} "
        f"inserted_character_rp_profiles={results['inserted_character_rp_profiles']} reused_character_rp_profiles={results['reused_character_rp_profiles']} "
        f"inserted_character_rp_examples={results['inserted_character_rp_examples']} reused_character_rp_examples={results['reused_character_rp_examples']} "
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


async def main() -> int:
    args = parse_args()
    query, params = build_target_query(args=args, use_epub_fallback=args.use_epub_fallback)
    conn = db_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = list(cur.fetchall())

        results = await build_context_rows(rows=rows, args=args, conn=conn)
        print_summary(results=results, apply=args.apply)
        if args.apply:
            conn.commit()
        else:
            conn.rollback()
        return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
